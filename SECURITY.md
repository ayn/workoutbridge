# Security

This early version runs locally. Only explicitly approved `publish --apply`
commands connect to Garmin using a user-supplied session directory. Tests use
fake accounts and never require credentials.

Keep sessions, ICS files, and review plans outside the checkout with restrictive
permissions. SQLite receipts are created with mode 0600; use a private directory
and retain the database to preserve duplicate protection. The local implementation
does not provide multi-user isolation or distributed locking for a hosted service.

Do not post secrets, private feed URLs, session files, or athlete information in
issues. Report vulnerabilities through GitHub private vulnerability reporting
on this repository's Security tab. If unavailable, open an issue requesting a
private reporting channel without disclosing exploit details.

Never attach an unredacted browser network capture. Such captures commonly
contain credentials, cookies, and personal workout data.
