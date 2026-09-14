# Troubleshooting & Configuration

## Environment Variables

| Variable | Description |
|----------|-------------|
| `URL_CHROME_PATH` | Custom Chrome executable path |

Output is stdout unless `-o/--output` is explicitly supplied. `URL_DATA_DIR` and
`URL_CHROME_PROFILE_DIR` are not used. Profiles are task-temporary by default.
Only `--profile <directory>` opts into persistent cookies/cache, under current user
authorization; that directory is not cleaned. Do not reuse an active daily profile.

## Common Issues

### 1. Chrome Not Found
**Symptom**: Script fails to launch browser.
**Fix**: Set `URL_CHROME_PATH` to your local Chrome/Chromium binary.

### 2. Timeout / Incomplete Load
**Symptom**: Page cuts off or loads partially.
**Fix**: Increase timeout: `--timeout 60000` (60s). Or use `--wait` mode for manual control.

### 3. Login Pages
**Fix**: Use `--wait` mode. The browser will open, allow you to log in manually, then capture upon pressing Enter in the terminal.

Only the newly created main-page target is extracted, including its redirects. Other
tabs and frames are excluded, even on the same domain. Timeouts and cleanup errors
are failures, not saved results. If browser exit cannot be confirmed, the retained
profile path is reported for manual recovery; forced termination may also leave it.
