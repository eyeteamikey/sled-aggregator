# Manual capture instructions

Fixture verification is not live verification. Never log in, register, solve CAPTCHA, submit a bid, or retain credentials/cookies.
For each task in `live-validation-tasks.json`, open only the registered entry URL, use the allowed method policy, and stop at any access control.
Record UTC time, final URL and redirects, status/content type, a bounded result, stable ID, public detail response, and attachment metadata without downloading during discovery.
Sanitize personal data, tokens, cookies, authorization headers, and vendor data before committing evidence.
Record login, CAPTCHA, rate-limit/Retry-After, robots, proxy, and network blockers exactly; never infer success through a blocker.
Promote to live verification only when the dated anonymous response matches the registered contract; require separate recurring evidence for production monitoring.
