# Alma Update Expired Users Emails

Script for updating email addresses of expired users in Alma ILS.

## What it does

- Processes a set of users from Alma (via set ID or TSV file)
- Identifies users expired for a configurable number of days
- Updates their email addresses using a configurable pattern
- Supports dry-run mode for safe testing

## Prerequisites

- Python 3.12+
- Poetry
- AlmaAPITK repository cloned locally (as sibling directory)
- Alma API credentials (environment variables)

## Installation

1. Clone AlmaAPITK (if not already done):
```bash
git clone https://github.com/hagaybar/AlmaAPITK.git ../AlmaAPITK
```

2. Install this project's dependencies (includes almaapitk as path dependency):
```bash
poetry install
```

That's it! No PYTHONPATH configuration needed.

## Configuration

Create config/email_update_config.json based on the example:

```bash
cp config/email_update_config.example.json config/email_update_config.json
# Edit with your settings
```

## Environment Variables

- `ALMA_SB_API_KEY` - Sandbox API key
- `ALMA_PROD_API_KEY` - Production API key

**Note: Secrets are NOT committed to the repository.**

## Usage

### Dry Run (default, safe)

```bash
poetry run python update_expired_user_emails.py --config config/email_update_config.json
```

Or explicitly with --dry-run flag:

```bash
poetry run python update_expired_user_emails.py --config config/email_update_config.json --dry-run
```

### Live Update

```bash
poetry run python update_expired_user_emails.py --config config/email_update_config.json --live
```

### With Set ID

```bash
poetry run python update_expired_user_emails.py --set-id 12345678900004146 --environment SANDBOX
```

### With TSV file

```bash
poetry run python update_expired_user_emails.py --tsv users.tsv --pattern "expired-{user_id}@example.edu"
```

### Create Sample Config

```bash
poetry run python update_expired_user_emails.py --create-sample-config
```

## CLI Options

| Option | Description |
|--------|-------------|
| `--config, -c` | JSON configuration file |
| `--environment, -e` | Alma environment (SANDBOX or PRODUCTION) |
| `--set-id` | Alma USER set ID |
| `--tsv` | TSV file with user IDs |
| `--pattern` | Email pattern with placeholders |
| `--days` | Days expired threshold |
| `--dry-run` | Perform dry run (default) |
| `--live` | Perform live update |
| `--max-users` | Maximum users to process |
| `--batch-size` | Batch size for processing |
| `--output-dir` | Output directory for logs/results |

## Email Pattern Placeholders

- `{user_id}` - User's primary ID
- `{first_name}` - User's first name (lowercase)
- `{last_name}` - User's last name (lowercase)
- `{original_email}` - Original email address
- `{original_local_part}` - Part before @ in original email
- `{original_domain}` - Domain part of original email

Example patterns:
- `expired-{user_id}@institution.edu`
- `{original_local_part}@{original_domain}.scrubbed`
- `disabled.{original_local_part}@{original_domain}`

## Output

- Logs are written to `./output/` directory
- Results CSV is generated with update details

## Testing

```bash
poetry run python scripts/smoke_project.py
poetry run python -m pytest tests/ -v
```

## Safety Features

1. **Dry-run mode is default** - No changes made unless explicitly using `--live`
2. **Production confirmation** - Requires typing 'YES' to confirm production updates
3. **Domain filtering** - Can limit updates to specific email domains
4. **Max users limit** - Can limit number of users processed for testing
5. **Backup logging** - Original emails logged before any changes

## License

Copyright (c) Tel Aviv University Library
