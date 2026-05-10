# Troubleshooting & Configuration

## Environment Variables

| Variable | Description |
|----------|-------------|
| `URL_CHROME_PATH` | Custom Chrome executable path |
| `URL_DATA_DIR` | Custom data directory |
| `URL_CHROME_PROFILE_DIR` | Custom Chrome profile directory |

## Common Issues

### 1. Chrome Not Found
**Symptom**: Script fails to launch browser.
**Fix**: Set `URL_CHROME_PATH` to your local Chrome/Chromium binary.

### 2. Timeout / Incomplete Load
**Symptom**: Page cuts off or loads partially.
**Fix**: Increase timeout: `--timeout 60000` (60s). Or use `--wait` mode for manual control.

### 3. Login Pages
**Fix**: Use `--wait` mode. The browser will open, allow you to log in manually, then capture upon pressing Enter in the terminal.
