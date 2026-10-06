# Security policy

AgniNetra has two public services: the research console and AgniNetra Live. Live has a
small API for Google sign in, qualifying rounds and community labels, backed by one SQLite
file. Reports about either are welcome.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
vulnerability reporting instead: open the **Security** tab of this repository and choose
**Report a vulnerability**. Describe what you found, how to reproduce it, and what an
attacker could do with it.

You can expect an acknowledgement within seven days. Once a fix is deployed, the report is
credited in the release notes unless you ask otherwise.

## In scope

- the Live server, `apps/live/serve.py` and `apps/live/community.py`: authentication,
  sessions, rate limits, the qualifying rounds and anything that lets one person cast more
  than one label per site;
- leaks of a player's email address, session or game data;
- the web apps: script injection, unsafe handling of feed or API data;
- anything that reveals the qualifying answers, which are kept only as HMACs.

## Out of scope

- denial of service by volume against the public deployments;
- findings that need a compromised device or browser;
- the third party data sources the project reads.

## Supported versions

Only the latest commit on each deployed branch, `console` and `agninetra`, is supported.
