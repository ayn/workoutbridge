"""Passkey-first multi-user gateway; each athlete has an isolated private application."""

import json
import os
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .accounts import MONTH, Accounts
from .scheduler import Scheduler
from .web import API_PREFIX, create_app


def create_hosted_app(
    root,
    origin,
    *,
    send_email,
    poll=True,
    commercial=True,
    vault_key=None,
    admin_email=None,
    billing_factory=None,
):
    root = Path(root)
    if urlsplit(origin).scheme != "https" or not urlsplit(origin).hostname:
        raise ValueError("Multi-user authentication requires an HTTPS origin")
    accounts = Accounts(root, plans=commercial)
    billing = billing_factory(accounts) if commercial and billing_factory else None
    rp = urlsplit(origin).hostname
    tenants = {}
    tenant_lock = threading.RLock()

    def tenant(user):
        with tenant_lock:
            if user not in tenants:
                folder = root / "users" / user
                from .vault import SessionVault

                vault = (
                    SessionVault(
                        folder / "sealed", Path("/tmp/prescribed-sessions") / user, vault_key
                    )
                    if vault_key is not None
                    else None
                )
                tenants[user] = create_app(
                    folder / "web",
                    origin,
                    secrets.token_urlsafe(40),
                    poll=False,
                    config_root=folder / "config",
                    tenant_id=user,
                    accounts=accounts,
                    vault=vault,
                )
            return tenants[user]

    def poll_user(user):
        tenant(user).state.poll_once()
        database = root / "users" / user / "web/web.sqlite"
        conn = sqlite3.connect(database, timeout=5)
        try:
            rules = [
                json.loads(r[0]) for r in conn.execute("SELECT body FROM objects WHERE kind='sync'")
            ]
            return {"checked": len(rules), "failed": sum(bool(r.get("error")) for r in rules)}
        finally:
            conn.close()

    scheduler = Scheduler(accounts, poll_user, commercial=commercial)

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()

        def dispatch():
            while not stop.is_set():
                scheduler.tick()
                if billing:
                    billing.reconcile_due()
                stop.wait(30)

        worker = threading.Thread(target=dispatch, daemon=True)
        if poll:
            worker.start()
        yield
        stop.set()
        if poll:
            worker.join(timeout=2)
        scheduler.close()
        for child in tenants.values():
            child.state.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.accounts = accounts
    app.state.tenant = tenant
    app.state.scheduler = scheduler
    app.state.billing = billing

    def cookie(response, name, value, age=MONTH):
        response.set_cookie(name, value, max_age=age, secure=True, httponly=True, samesite="strict")

    @app.middleware("http")
    async def protect(request, call_next):
        if request.headers.get("host") != urlsplit(origin).netloc:
            return JSONResponse({"detail": "Invalid host"}, status_code=400)
        if request.url.path.startswith("/api/"):
            webhook = request.url.path == API_PREFIX + "/billing/webhook"
            if not webhook and request.method != "GET" and request.headers.get("origin") != origin:
                return JSONResponse({"detail": "Invalid origin"}, status_code=403)
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > (1048576 if webhook else 16384):
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            user = accounts.session_user(request.cookies.get("prescribed_session", ""))
            request.state.hosted_user = user
            public = request.url.path.startswith(API_PREFIX + "/auth/") or webhook
            if not public and request.url.path != API_PREFIX + "/config":
                if (
                    user is None
                    or not accounts.user(user)["verified"]
                    or not accounts.credential_ids(user)
                ):
                    return JSONResponse({"detail": "Sign in required"}, status_code=401)
            if request.method == "POST":
                try:
                    # Remote address is the direct peer, never an untrusted forwarded header.
                    # Apache must preserve per-client limits separately at the edge.
                    peer = request.client.host if request.client else "unknown"
                    if public and not webhook:
                        accounts.throttle("auth:" + peer, limit=30, seconds=300)
                    elif request.url.path.endswith(("/preview", "/publish")):
                        accounts.throttle(
                            "manual:" + str(user) + request.url.path.rsplit("/", 1)[-1],
                            limit=1,
                            seconds=60,
                        )
                except PermissionError:
                    return JSONResponse(
                        {"detail": "Too many requests; try again shortly"}, status_code=429
                    )
        response = await call_next(request)
        session_token = request.cookies.get("prescribed_session", "")
        if (
            session_token
            and response.status_code < 400
            and request.url.path.startswith(API_PREFIX + "/")
            and request.url.path != API_PREFIX + "/logout"
            and not request.url.path.startswith(API_PREFIX + "/auth/")
        ):
            if accounts.renew_session(session_token):
                cookie(response, "prescribed_session", session_token)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse(
            {"detail": "Request could not be completed. Check values or restart sign-in."},
            status_code=400,
        )

    @app.exception_handler(PermissionError)
    async def forbidden(request, error):
        return JSONResponse({"detail": "This action is not permitted"}, status_code=403)

    @app.get("/health")
    def health():
        with accounts.db() as db:
            db.execute("SELECT 1")
        return {"status": "ok"}

    @app.get(API_PREFIX + "/config")
    def config():
        return {"multiuser": True, "commercial": commercial, "brand": "Prescribed"}

    @app.post(API_PREFIX + "/auth/signup")
    def signup(body: dict):
        email = body.get("email")
        accounts.throttle("email:" + str(email).strip().lower(), limit=1, seconds=300)
        user = accounts.create_user(email)
        if not accounts.credential_ids(user):
            code = body.get("invite")
            if code:
                accounts.accept_invite(user, code)
            token = accounts.email_token(user)
            try:
                send_email(email, origin + "/#verify=" + token)
            except Exception:  # noqa: BLE001 - redact provider errors and never echo email tokens.
                raise HTTPException(
                    503, "Verification email could not be sent. Try again later."
                ) from None
        return {
            "ok": True,
            "message": "Check your email. Existing members should sign in with a passkey.",
        }

    @app.post(API_PREFIX + "/auth/verify")
    def verify_email(body: dict):
        user = accounts.consume_email_token(body.get("token", ""))
        if accounts.credential_ids(user):
            raise ValueError("Use your existing passkey")
        enrollment = accounts.challenge("enrollment", {"user": user})
        response = JSONResponse({"ok": True})
        cookie(response, "prescribed_enrollment", enrollment, 300)
        return response

    @app.post(API_PREFIX + "/auth/register/options")
    def register_options(request: Request):
        signed_user = request.state.hosted_user
        if signed_user:
            user = signed_user
        else:
            pending = accounts.read_challenge(
                request.cookies.get("prescribed_enrollment", ""), "enrollment"
            )
            user = pending["user"]
            if accounts.credential_ids(user):
                raise ValueError("Use existing passkey")
        value = accounts.user(user)
        if not value["verified"]:
            raise ValueError("Verify email first")
        options = generate_registration_options(
            rp_id=rp,
            rp_name="Prescribed",
            user_id=user.encode(),
            user_name=value["email"],
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(key))
                for key in accounts.credential_ids(user)
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        key = accounts.challenge(
            "register",
            {
                "user": user,
                "challenge": bytes_to_base64url(options.challenge),
                "initial": not bool(signed_user),
            },
        )
        response = JSONResponse(json.loads(options_to_json(options)))
        cookie(response, "prescribed_challenge", key, 300)
        return response

    @app.post(API_PREFIX + "/auth/register/finish")
    def register_finish(request: Request, body: dict):
        saved = accounts.take_challenge(request.cookies.get("prescribed_challenge", ""), "register")
        user = saved["user"]
        if saved["initial"]:
            if accounts.credential_ids(user):
                raise ValueError("Already enrolled")
        elif request.state.hosted_user != user:
            raise ValueError("Session changed")
        try:
            result = verify_registration_response(
                credential=body.get("credential"),
                expected_challenge=base64url_to_bytes(saved["challenge"]),
                expected_origin=origin,
                expected_rp_id=rp,
                require_user_verification=True,
            )
        except Exception:  # noqa: BLE001 - malformed authenticator input must fail closed.
            raise ValueError("Passkey verification failed") from None
        accounts.add_credential(
            user,
            bytes_to_base64url(result.credential_id),
            result.credential_public_key,
            result.sign_count,
            initial=saved["initial"],
        )
        if saved["initial"]:
            accounts.start_trial(user)
        if admin_email and accounts.user(user)["email"] == admin_email.strip().lower():
            accounts.set_admin(user, True)
        response = JSONResponse({"ok": True})
        cookie(response, "prescribed_session", accounts.new_session(user))
        response.delete_cookie("prescribed_challenge")
        response.delete_cookie("prescribed_enrollment")
        return response

    @app.post(API_PREFIX + "/auth/login/options")
    def login_options():
        options = generate_authentication_options(
            rp_id=rp, user_verification=UserVerificationRequirement.REQUIRED
        )
        key = accounts.challenge("login", {"challenge": bytes_to_base64url(options.challenge)})
        response = JSONResponse(json.loads(options_to_json(options)))
        cookie(response, "prescribed_challenge", key, 300)
        return response

    @app.post(API_PREFIX + "/auth/login/finish")
    def login_finish(request: Request, body: dict):
        saved = accounts.take_challenge(request.cookies.get("prescribed_challenge", ""), "login")
        credential = body.get("credential")
        old = (
            accounts.credential(credential.get("id", "")) if isinstance(credential, dict) else None
        )
        if not old:
            raise ValueError("Unknown credential")
        try:
            result = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(saved["challenge"]),
                expected_origin=origin,
                expected_rp_id=rp,
                credential_public_key=old["public_key"],
                credential_current_sign_count=old["counter"],
                require_user_verification=True,
            )
        except Exception:  # noqa: BLE001 - malformed authenticator input must fail closed.
            raise ValueError("Passkey verification failed") from None
        value = accounts.user(old["user"])
        if not value["verified"] or value["disabled"]:
            raise ValueError("Account unavailable")
        accounts.counter(old["id"], old["counter"], result.new_sign_count)
        response = JSONResponse({"ok": True})
        cookie(response, "prescribed_session", accounts.new_session(old["user"]))
        response.delete_cookie("prescribed_challenge")
        return response

    @app.post(API_PREFIX + "/logout")
    def logout(request: Request):
        accounts.logout(request.cookies.get("prescribed_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("prescribed_session")
        return response

    @app.get(API_PREFIX + "/account")
    def account(request: Request):
        user = request.state.hosted_user
        value = accounts.user(user)
        return {
            "id": user,
            "email": value["email"],
            "admin": bool(value["admin"]),
            "entitlements": accounts.entitlements(user)
            if commercial
            else {"plan": "self-hosted", "interval": 900, "multiple_destinations": True},
            "free_provider": value["free_provider"],
            "invite_url": origin + "/?invite=" + accounts.invite(user),
            "passkeys": len(accounts.credential_ids(user)),
            "schedule": scheduler.status(user),
            "referrals": accounts.referral_tracker(user),
            "billing": billing_status(user),
        }

    def billing_status(user):
        row = billing.status(user) if billing else None
        return {
            "enabled": bool(billing),
            "connected": bool(row),
            "status": row["status"] if row else None,
            "paid_until": row["paid_until"] if row else None,
            "cancel_pending": bool(row and row["cancel_pending"]),
            "checked": row["checked"] if row else None,
            "plan": row["plan"] if row else None,
        }

    @app.post(API_PREFIX + "/billing/webhook")
    async def billing_webhook(request: Request):
        if not billing:
            raise HTTPException(503, "Billing is not configured")
        # Signature verification requires the original bytes, never parsed/re-encoded JSON.
        from starlette.concurrency import run_in_threadpool

        try:
            await run_in_threadpool(
                billing.webhook, await request.body(), request.headers.get("stripe-signature", "")
            )
        except RuntimeError:
            raise HTTPException(503, "Billing temporarily unavailable") from None
        return {"ok": True}

    @app.post(API_PREFIX + "/billing/{action}")
    def billing_action(request: Request, action: str, body: dict):
        if not billing:
            raise HTTPException(503, "Billing is not configured")
        user = request.state.hosted_user
        try:
            if action == "checkout":
                return {"url": billing.checkout(user, body.get("plan", "monthly"))}
            if action == "portal":
                return {"url": billing.portal(user)}
            if action == "change-plan":
                return {"url": billing.portal(user, change=True)}
            if action == "refresh":
                accounts.throttle("billing-refresh:" + user, limit=1, seconds=60)
                billing.reconcile(user)
                return billing_status(user)
        except RuntimeError:
            raise HTTPException(503, "Billing temporarily unavailable") from None
        raise HTTPException(404, "Unknown billing action")

    @app.post(API_PREFIX + "/account/resume")
    def resume(request: Request, body: dict):
        if body.get("acknowledge_review") is not True:
            raise HTTPException(422, "Review publishing history before resuming")
        scheduler.resume(request.state.hosted_user)
        return {"ok": True}

    @app.post(API_PREFIX + "/account/provider")
    def free_provider(request: Request, body: dict):
        accounts.choose_provider(request.state.hosted_user, body.get("provider"))
        return {"ok": True}

    @app.post(API_PREFIX + "/account/frequency")
    def frequency(request: Request, body: dict):
        scheduler.configure(request.state.hosted_user, body.get("seconds"))
        return {"ok": True}

    @app.get(API_PREFIX + "/admin")
    def admin(request: Request):
        accounts.audit_view(request.state.hosted_user)
        result = accounts.admin_users(request.state.hosted_user)
        totals = {
            "users": len(result["users"]),
            "verified": 0,
            "sources": 0,
            "syncs": 0,
            "automatic": 0,
            "blocked": 0,
        }
        for user in result["users"]:
            totals["verified"] += bool(user["verified"])
            database = root / "users" / user["id"] / "web/web.sqlite"
            counts = {"sources": 0, "syncs": 0, "automatic": 0, "blocked": 0}
            if database.exists():
                conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
                try:
                    counts["sources"] = conn.execute(
                        "SELECT count(*) FROM objects WHERE kind='source'"
                    ).fetchone()[0]
                    for row in conn.execute("SELECT body FROM objects WHERE kind='sync'"):
                        value = json.loads(row[0])
                        counts["syncs"] += 1
                        counts["automatic"] += bool(value.get("automatic"))
                        counts["blocked"] += bool(value.get("auto_blocked"))
                finally:
                    conn.close()
            user["usage"] = counts
            user["schedule"] = scheduler.status(user["id"])
            for key in counts:
                totals[key] += counts[key]
        result["totals"] = totals
        return result

    @app.post(API_PREFIX + "/admin/gifts")
    def gift(request: Request, body: dict):
        key = accounts.gift(
            request.state.hosted_user,
            body.get("user"),
            days=body.get("days"),
            reason=body.get("reason"),
        )
        return {"id": key}

    @app.post(API_PREFIX + "/admin/gifts/{key}/revoke")
    def revoke(request: Request, key: str):
        accounts.revoke(request.state.hosted_user, key)
        return {"ok": True}

    class TenantDispatch:
        async def __call__(self, scope, receive, send):
            user = scope["state"]["hosted_user"]
            await tenant(user)(scope, receive, send)

    app.router.routes.append(
        Route(API_PREFIX + "/{path:path}", TenantDispatch(), methods=["GET", "POST"])
    )
    static = Path(os.environ.get("WORKOUTBRIDGE_STATIC_DIR", "web/dist"))
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app
