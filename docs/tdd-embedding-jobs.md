# Embedding hooks

These generic hooks let an embedding application provide its own operation lock
and request transport. DIY retains the default RLock and direct HTTP transport;
no queue, Redis, billing or multi-user dependency is added.

Red: `uv run --extra web python -m unittest discover -s tests -p test_web_extensions.py`
failed because `create_app` did not accept `operation`. `npm test -- --run src/App.test.tsx`
failed because the injected request function was never called.

Green: 192 Python tests, 19 frontend tests, and the isolated DIY startup smoke
passed. The action hook only accepts preview, publish and automatic and delegates
to the same validation/receipt handling used by the HTTP endpoints.

The deployment instructions also explain device key expiry for unattended
Tailscale sidecars, distinct from enrollment auth-key expiry.
