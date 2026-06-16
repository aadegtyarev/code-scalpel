# Fix Link Checker

The --check command hangs on large directories because it does HTTP requests to every external URL sequentially with no rate limiting. Analyze the code and fix it.
