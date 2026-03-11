#!/usr/bin/env python3
"""
Update Expired User Emails Script
Updates email addresses for users expired for specified number of days from Alma sets.

Usage:
    python update_expired_user_emails.py --set-id 12345678900004146 --environment SANDBOX
    python update_expired_user_emails.py --config config.json --live
    python update_expired_user_emails.py --tsv users.tsv --pattern "expired-{user_id}@university.edu"
"""

import argparse
import json
import csv
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import logging

# Import from almaapitk public API
# Requires: AlmaAPITK cloned locally with PYTHONPATH including its src/ directory
# Example: export PYTHONPATH=/path/to/AlmaAPITK/src:$PYTHONPATH
from almaapitk import (
    AlmaAPIClient,
    AlmaAPIError,
    AlmaValidationError,
    Admin,
    Users,
)


class EmailUpdateScript:
    """
    Main script class for updating expired user emails.
    Orchestrates the complete workflow from set processing to email updates.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the script with configuration.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.results = {
            'start_time': datetime.now(),
            'total_users_found': 0,
            'users_qualified': 0,
            'emails_updated': 0,
            'errors': [],
            'user_details': []
        }

        # Initialize logging
        self.setup_logging()

        # Initialize Alma clients
        self.logger.info("Initializing Alma API clients...")
        try:
            self.client = AlmaAPIClient(self.config['environment'])
            self.admin = Admin(self.client)
            self.users = Users(self.client)  # Fixed: removed log_file parameter

            # Test connections
            if not self.client.test_connection():
                raise RuntimeError("Failed to connect to Alma API")

            self.logger.info(f"✓ Connected to Alma API ({self.config['environment']})")

        except Exception as e:
            self.logger.error(f"Failed to initialize Alma clients: {e}")
            raise

    def setup_logging(self) -> None:
        """Setup logging configuration."""
        # Create output directory
        output_dir = Path(self.config.get('output_dir', './output'))
        output_dir.mkdir(parents=True, exist_ok=True)

        # Setup logger
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = output_dir / f"email_update_{timestamp}.log"

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )

        self.logger = logging.getLogger('EmailUpdateScript')
        self.logger.info(f"Email update script started - Log file: {log_file}")

    def get_log_file_path(self) -> str:
        """Get the log file path for the users domain."""
        output_dir = Path(self.config.get('output_dir', './output'))
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return str(output_dir / f"users_processing_{timestamp}.log")

    def display_configuration(self) -> None:
        """Display current configuration."""
        self.logger.info("\n" + "="*60)
        self.logger.info("EMAIL UPDATE SCRIPT CONFIGURATION")
        self.logger.info("="*60)
        self.logger.info(f"Environment: {self.config['environment']}")
        self.logger.info(f"Mode: {'DRY RUN' if self.config['dry_run'] else 'LIVE UPDATE'}")

        if self.config.get('set_id'):
            self.logger.info(f"Set ID: {self.config['set_id']}")
        if self.config.get('tsv_file'):
            self.logger.info(f"TSV File: {self.config['tsv_file']}")

        self.logger.info(f"Days Expired: {self.config['days_expired']}")
        self.logger.info(f"Email Pattern: {self.config['email_pattern']}")

        if self.config.get('max_users'):
            self.logger.info(f"Max Users: {self.config['max_users']}")

        self.logger.info(f"Batch Size: {self.config['batch_size']}")
        self.logger.info(f"Output Directory: {self.config['output_dir']}")
        self.logger.info("="*60)

    def confirm_execution(self) -> bool:
        """
        Get user confirmation for script execution.

        Returns:
            True if user confirms, False otherwise
        """
        if self.config['environment'] == 'PRODUCTION' and not self.config['dry_run']:
            self.logger.warning("\n⚠️  WARNING: PRODUCTION ENVIRONMENT - LIVE UPDATE MODE ⚠️")
            self.logger.warning("This will make actual changes to user email addresses in production!")

            response = input("\nType 'YES' to confirm production update: ").strip()
            if response != 'YES':
                self.logger.info("Operation cancelled by user")
                return False

        elif not self.config['dry_run']:
            response = input(f"\nConfirm live update in {self.config['environment']}? (y/n): ").strip().lower()
            if response != 'y':
                self.logger.info("Operation cancelled by user")
                return False

        return True

    def get_user_ids_from_set(self) -> List[str]:
        """
        Get user IDs from Alma set.

        Returns:
            List of user IDs

        Raises:
            RuntimeError: If set processing fails
        """
        set_id = self.config['set_id']
        self.logger.info(f"Processing Alma set: {set_id}")

        try:
            # Validate set
            set_info = self.admin.validate_user_set(set_id)
            self.logger.info(f"Set validated: {set_info['name']} ({set_info['total_members']} members)")

            # Get metadata and warnings
            metadata = self.admin.get_set_metadata_and_member_count(set_id)

            if metadata['processing_warnings']:
                self.logger.warning("Set processing warnings:")
                for warning in metadata['processing_warnings']:
                    self.logger.warning(f"  - {warning}")

            # Get user IDs
            user_ids = self.admin.get_user_set_members(set_id)
            self.logger.info(f"Retrieved {len(user_ids)} user IDs from set")

            return user_ids

        except (AlmaAPIError, AlmaValidationError) as e:
            raise RuntimeError(f"Set processing failed: {e}")

    def get_user_ids_from_tsv(self) -> Tuple[List[str], Dict[str, str]]:
        """
        Get user IDs from TSV file with optional original emails for revert.

        Supports two formats:
        - 1 column: user_id (normal operation)
        - 2 columns: user_id<tab>original_email (revert operation)

        Returns:
            Tuple of (user_ids_list, original_emails_dict)
            - user_ids_list: List of user IDs
            - original_emails_dict: Dict mapping user_id -> original_email (empty if 1 column)

        Raises:
            RuntimeError: If TSV processing fails
        """
        tsv_file = self.config['tsv_file']
        self.logger.info(f"Processing TSV file: {tsv_file}")

        if not os.path.exists(tsv_file):
            raise RuntimeError(f"TSV file not found: {tsv_file}")

        try:
            user_ids = []
            original_emails = {}
            column_count = None

            with open(tsv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter='\t')

                for row_num, row in enumerate(reader, 1):
                    if not row or not row[0].strip():  # Skip empty rows
                        continue

                    # Determine format on first data row
                    if column_count is None:
                        column_count = len(row)
                        if column_count == 1:
                            self.logger.info("TSV format: 1 column (user_id only) - normal operation")
                        elif column_count == 2:
                            self.logger.info("TSV format: 2 columns (user_id + original_email) - revert operation")
                        else:
                            raise RuntimeError(f"Invalid TSV format: expected 1 or 2 columns, found {column_count} in row {row_num}")

                    # Validate consistent column count
                    if len(row) != column_count:
                        raise RuntimeError(f"Inconsistent column count in row {row_num}: expected {column_count}, found {len(row)}")

                    # Extract data
                    user_id = row[0].strip()
                    if not user_id:
                        self.logger.warning(f"Empty user_id in row {row_num}, skipping")
                        continue

                    user_ids.append(user_id)

                    # Handle original email if present
                    if column_count == 2:
                        original_email = row[1].strip()
                        if not original_email:
                            raise RuntimeError(f"Empty original_email in row {row_num} (required for 2-column format)")

                        # Validate email format
                        if '@' not in original_email:
                            raise RuntimeError(f"Invalid email format in row {row_num}: {original_email}")

                        original_emails[user_id] = original_email
                        self.logger.debug(f"Row {row_num}: {user_id} -> {original_email}")
                    else:
                        self.logger.debug(f"Row {row_num}: {user_id}")

            # Summary logging
            if column_count == 1:
                self.logger.info(f"Retrieved {len(user_ids)} user IDs from TSV file")
            else:
                self.logger.info(f"Retrieved {len(user_ids)} user IDs with original emails from TSV file")
                self.logger.info(f"Revert mode: will use provided original emails instead of current user emails")

            return user_ids, original_emails

        except Exception as e:
            raise RuntimeError(f"TSV processing failed: {e}")

    def process_users_for_qualification(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Process users to determine qualification for email update.

        Args:
            user_ids: List of user IDs to process

        Returns:
            List of processing results
        """
        # Apply max_users limit if specified
        if self.config.get('max_users'):
            original_count = len(user_ids)
            user_ids = user_ids[:self.config['max_users']]
            self.logger.info(f"Limited processing to {len(user_ids)} users (from {original_count})")

        self.results['total_users_found'] = len(user_ids)

        # Convert days to years for the users domain
        years_threshold = self.config['days_expired'] / 365.25

        self.logger.info(f"Processing {len(user_ids)} users for qualification...")
        self.logger.info(f"Threshold: {self.config['days_expired']} days ({years_threshold:.1f} years)")

        # Process users in batches
        batch_results = self.users.process_users_batch(
            user_ids,
            years_threshold=years_threshold,
            max_workers=1  # Conservative for API protection
        )

        # Filter qualified users and enhance with email validation
        qualified_users = []
        for result in batch_results:
            if result['qualifies_for_update']:
                # Additional validation: check for preferred email
                enhanced_result = self.validate_user_email_structure(result)
                if enhanced_result['has_preferred_email']:
                    qualified_users.append(enhanced_result)

        self.results['users_qualified'] = len(qualified_users)
        self.logger.info(f"✓ Found {len(qualified_users)} users qualified for email update")

        return qualified_users

    def validate_user_email_structure(self, user_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate that user has a preferred email that can be updated.

        Args:
            user_result: User processing result from users domain

        Returns:
            Enhanced result with email validation
        """
        enhanced = user_result.copy()
        enhanced['has_preferred_email'] = False
        enhanced['preferred_email'] = None
        enhanced['preferred_email_info'] = None
        enhanced['domain_filtered'] = False

        try:
            user_data = user_result['user_data']
            emails = user_result['emails']

            # Find preferred email
            preferred_email = None
            for email_info in emails:
                if email_info.get('preferred', False):
                    preferred_email = email_info
                    break

            if preferred_email:
                email_address = preferred_email['address']

                # Check domain filter
                if not self.is_domain_allowed(email_address):
                    self.logger.debug(f"User {user_result['user_id']}: email domain not allowed: {email_address}")
                    enhanced['domain_filtered'] = True
                    self.results['errors'].append({
                        'user_id': user_result['user_id'],
                        'error_type': 'domain_not_allowed',
                        'error_message': f'Email domain not in allowed domains: {email_address}'
                    })
                    return enhanced

                # Domain is allowed, proceed
                enhanced['has_preferred_email'] = True
                enhanced['preferred_email'] = email_address
                enhanced['preferred_email_info'] = preferred_email
                self.logger.debug(f"User {user_result['user_id']}: preferred email found and domain allowed: {email_address}")
            else:
                self.logger.warning(f"User {user_result['user_id']}: no preferred email found")
                self.results['errors'].append({
                    'user_id': user_result['user_id'],
                    'error_type': 'no_preferred_email',
                    'error_message': 'No preferred email found'
                })

        except Exception as e:
            self.logger.error(f"Error validating email structure for user {user_result['user_id']}: {e}")
            enhanced['validation_error'] = str(e)

        return enhanced

    def generate_new_email(self, user_data: Dict[str, Any], original_email: str = None, override_original_email: str = None) -> str:
        """
        Generate new email address using the configured pattern.
        Supports preserving original domain and email parts.

        Args:
            user_data: User data from Alma
            original_email: Original preferred email address from user data (optional)
            override_original_email: Original email from TSV file (for revert operations)

        Returns:
            Generated email address

        Raises:
            ValueError: If email generation fails
        """
        pattern = self.config['email_pattern']

        try:
            # Extract user information
            user_id = user_data.get('primary_id', '')
            first_name = user_data.get('first_name', '').lower()
            last_name = user_data.get('last_name', '').lower()

            if not user_id:
                raise ValueError("User ID not found in user data")

            # Determine which original email to use
            email_to_process = override_original_email or original_email

            if not email_to_process:
                raise ValueError("No original email provided (neither from user data nor TSV override)")

            # Extract original email parts
            if '@' not in email_to_process:
                raise ValueError(f"Invalid email format: {email_to_process}")

            local_part, domain = email_to_process.split('@', 1)

            # Log which email source is being used
            if override_original_email:
                self.logger.debug(f"Using TSV-provided original email for {user_id}: {override_original_email}")
            else:
                self.logger.debug(f"Using current user email for {user_id}: {original_email}")

            # Generate email with enhanced placeholders
            new_email = pattern.format(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                original_email=email_to_process,
                original_local_part=local_part,
                original_domain=domain
            )

            return new_email

        except KeyError as e:
            raise ValueError(f"Unknown placeholder in email pattern: {e}")
        except Exception as e:
            raise ValueError(f"Email generation failed: {e}")

    def backup_original_email(self, user_id: str, original_email: str) -> None:
        """
        Log original email for backup purposes.

        Args:
            user_id: User identifier
            original_email: Original email address
        """
        self.logger.info(f"BACKUP: User {user_id} original preferred email: {original_email}")

    def is_domain_allowed(self, email: str) -> bool:
        """
        Check if email domain is in allowed domains list.

        Args:
            email: Email address to check

        Returns:
            True if domain is allowed or no domain filter configured, False otherwise
        """
        allowed_domains = self.config.get('allowed_domains', [])

        # If no domain filter configured, allow all domains
        if not allowed_domains:
            return True

        # Validate email format
        if not email or '@' not in email:
            self.logger.warning(f"Invalid email format for domain check: {email}")
            return False

        # Extract domain from email (including @)
        email_domain = '@' + email.split('@')[1]

        # Check if email domain matches any allowed domain
        for allowed_domain in allowed_domains:
            if email_domain.lower() == allowed_domain.lower():
                return True

        self.logger.debug(f"Email domain '{email_domain}' not in allowed domains: {allowed_domains}")
        return False

    def update_user_emails(self, qualified_users: List[Dict[str, Any]], tsv_original_emails: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Update email addresses for qualified users.

        Args:
            qualified_users: List of users qualified for email update
            tsv_original_emails: Dict mapping user_id -> original_email from TSV (for revert operations)

        Returns:
            List of update results
        """
        if not qualified_users:
            self.logger.info("No qualified users to process")
            return []

        # Apply max_users limit to qualified users as final safety check
        if self.config.get('max_users') and len(qualified_users) > self.config['max_users']:
            original_count = len(qualified_users)
            qualified_users = qualified_users[:self.config['max_users']]
            self.logger.warning(f"Limited email updates to {len(qualified_users)} users (from {original_count} qualified)")

        # Check if we're in revert mode
        is_revert_mode = tsv_original_emails is not None and len(tsv_original_emails) > 0

        if is_revert_mode:
            self.logger.info(f"REVERT MODE: Using original emails from TSV for {len(tsv_original_emails)} users")

        self.logger.info(f"Starting email updates for {len(qualified_users)} users...")
        mode = "DRY RUN" if self.config['dry_run'] else "LIVE UPDATE"
        self.logger.info(f"Mode: {mode}")

        # Prepare email updates
        email_updates = []
        for user_result in qualified_users:
            try:
                user_data = user_result['user_data']
                user_id = user_result['user_id']
                current_email = user_result['preferred_email']

                # Determine original email source
                if is_revert_mode and user_id in tsv_original_emails:
                    # Revert mode: use TSV-provided original email
                    tsv_original_email = tsv_original_emails[user_id]
                    actual_original_email = tsv_original_email

                    # Generate new email using TSV original
                    new_email = self.generate_new_email(
                        user_data,
                        original_email=current_email,
                        override_original_email=tsv_original_email
                    )

                    self.logger.debug(f"REVERT: {user_id} - TSV original: {tsv_original_email}, Current: {current_email}, New: {new_email}")

                elif is_revert_mode:
                    # Revert mode but user not in TSV - skip with warning
                    self.logger.warning(f"User {user_id} not found in TSV original emails, skipping")
                    self.results['errors'].append({
                        'user_id': user_id,
                        'error_type': 'missing_tsv_original',
                        'error_message': 'User not found in TSV original emails for revert operation'
                    })
                    continue

                else:
                    # Normal mode: use current user email as original
                    actual_original_email = current_email
                    new_email = self.generate_new_email(user_data, original_email=current_email)

                    self.logger.debug(f"NORMAL: {user_id} - Current/Original: {current_email}, New: {new_email}")

                # Backup original email (log the true original, not current)
                self.backup_original_email(user_id, actual_original_email)

                email_updates.append({
                    'user_id': user_id,
                    'original_email': actual_original_email,
                    'current_email': current_email,
                    'new_email': new_email,
                    'user_result': user_result,  # Keep full result for reporting
                    'is_revert': is_revert_mode
                })

            except Exception as e:
                self.logger.error(f"Error preparing email update for user {user_result['user_id']}: {e}")
                self.results['errors'].append({
                    'user_id': user_result['user_id'],
                    'error_type': 'email_generation_failed',
                    'error_message': str(e)
                })

        if not email_updates:
            self.logger.warning("No email updates prepared")
            return []

        # Perform bulk email updates
        update_results = self.users.bulk_update_emails(
            email_updates,
            dry_run=self.config['dry_run']
        )

        # Process results with enhanced original email tracking
        successful_updates = sum(1 for r in update_results if r['success'])
        self.results['emails_updated'] = successful_updates

        # Log detailed results
        for result in update_results:
            # Find the original email from our email_updates list
            original_email = 'Unknown'
            current_email = 'Unknown'
            is_revert = False

            for update in email_updates:
                if update['user_id'] == result['user_id']:
                    original_email = update['original_email']
                    current_email = update['current_email']
                    is_revert = update['is_revert']
                    break

            user_detail = {
                'user_id': result['user_id'],
                'original_email': original_email,
                'current_email': current_email,
                'new_email': result['new_email'],
                'success': result['success'],
                'error': result.get('error'),
                'dry_run': result['dry_run'],
                'is_revert': is_revert
            }
            self.results['user_details'].append(user_detail)

            if not result['success']:
                self.results['errors'].append({
                    'user_id': result['user_id'],
                    'error_type': 'email_update_failed',
                    'error_message': result.get('error', 'Unknown error')
                })

        operation_type = "REVERT" if is_revert_mode else "UPDATE"
        self.logger.info(f"Email {operation_type.lower()} complete: {successful_updates}/{len(email_updates)} successful")

        return update_results

    def export_results_to_csv(self) -> str:
        """
        Export results to CSV file.

        Returns:
            Path to CSV file
        """
        output_dir = Path(self.config['output_dir'])
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        mode = "dry_run" if self.config['dry_run'] else "live_update"
        csv_file = output_dir / f"email_update_results_{mode}_{timestamp}.csv"

        try:
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Write header
                writer.writerow([
                    'User_ID', 'Original_Email', 'Current_Email', 'New_Email', 'Success',
                    'Error', 'Mode', 'Is_Revert', 'Timestamp'
                ])

                # Write data
                for detail in self.results['user_details']:
                    writer.writerow([
                        detail['user_id'],
                        detail.get('original_email', ''),
                        detail.get('current_email', ''),
                        detail['new_email'],
                        detail['success'],
                        detail.get('error', ''),
                        'DRY_RUN' if detail['dry_run'] else 'LIVE_UPDATE',
                        detail.get('is_revert', False),
                        self.results['start_time'].strftime('%Y-%m-%d %H:%M:%S')
                    ])

            self.logger.info(f"✓ Results exported to CSV: {csv_file}")
            return str(csv_file)

        except Exception as e:
            self.logger.error(f"Failed to export CSV: {e}")
            return ""

    def generate_summary_report(self) -> None:
        """Generate and display summary report."""
        end_time = datetime.now()
        duration = end_time - self.results['start_time']

        self.logger.info("\n" + "="*60)
        self.logger.info("EMAIL UPDATE SUMMARY REPORT")
        self.logger.info("="*60)
        self.logger.info(f"Start Time: {self.results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Duration: {duration}")
        self.logger.info(f"Environment: {self.config['environment']}")
        self.logger.info(f"Mode: {'DRY RUN' if self.config['dry_run'] else 'LIVE UPDATE'}")

        self.logger.info(f"\nProcessing Results:")
        self.logger.info(f"  Total users found: {self.results['total_users_found']}")
        self.logger.info(f"  Users qualified: {self.results['users_qualified']}")
        self.logger.info(f"  Emails updated: {self.results['emails_updated']}")
        self.logger.info(f"  Errors: {len(self.results['errors'])}")

        if self.results['users_qualified'] > 0:
            success_rate = (self.results['emails_updated'] / self.results['users_qualified']) * 100
            self.logger.info(f"  Success rate: {success_rate:.1f}%")

        if self.results['errors']:
            self.logger.info(f"\nError Summary:")
            error_types = {}
            for error in self.results['errors']:
                error_type = error['error_type']
                error_types[error_type] = error_types.get(error_type, 0) + 1

            for error_type, count in error_types.items():
                self.logger.info(f"  {error_type}: {count}")

        self.logger.info("="*60)

    def run(self) -> bool:
        """
        Run the complete email update workflow.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Display configuration
            self.display_configuration()

            # Get user confirmation
            if not self.confirm_execution():
                return False

            # Step 1: Get user IDs
            tsv_original_emails = None
            if self.config.get('set_id'):
                user_ids = self.get_user_ids_from_set()
            elif self.config.get('tsv_file'):
                user_ids, tsv_original_emails = self.get_user_ids_from_tsv()
            else:
                raise RuntimeError("Either set_id or tsv_file must be specified")

            if not user_ids:
                self.logger.warning("No user IDs found to process")
                return True

            # Step 2: Process users for qualification
            qualified_users = self.process_users_for_qualification(user_ids)

            if not qualified_users:
                self.logger.warning("No users qualified for email update")
                self.generate_summary_report()
                return True

            # Step 3: Update emails
            update_results = self.update_user_emails(qualified_users, tsv_original_emails)

            # Step 4: Export results
            self.export_results_to_csv()

            # Step 5: Generate summary
            self.generate_summary_report()

            return True

        except Exception as e:
            self.logger.error(f"Script execution failed: {e}")
            self.generate_summary_report()
            return False

def load_config_file(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to config file

    Returns:
        Configuration dictionary
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file: {e}")
        sys.exit(1)

def create_sample_config(output_path: str = "email_update_config.json") -> str:
    """Create a sample configuration file."""
    sample_config = {
        "environment": "SANDBOX",
        "set_id": "12345678900004146",
        "email_pattern": "expired-{user_id}@institution.edu",
        "days_expired": 730,
        "dry_run": True,
        "max_users": None,
        "batch_size": 50,
        "output_dir": "./output"
    }

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sample_config, f, indent=2)
        print(f"✓ Sample configuration created: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error creating sample config: {e}")
        sys.exit(1)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Update email addresses for expired users from Alma sets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with set ID
  python update_expired_user_emails.py --set-id 12345678900004146 --environment SANDBOX

  # Using config file
  python update_expired_user_emails.py --config config.json

  # TSV file input
  python update_expired_user_emails.py --tsv users.tsv --pattern "expired-{user_id}@university.edu"

  # Live update (careful!)
  python update_expired_user_emails.py --set-id 12345678900004146 --live
        """
    )

    # Configuration source
    parser.add_argument("--config", "-c", help="JSON configuration file")
    parser.add_argument("--create-sample-config", action="store_true",
                       help="Create sample configuration file and exit")

    # Core options
    parser.add_argument("--environment", "-e", choices=["SANDBOX", "PRODUCTION"],
                       help="Alma environment")
    parser.add_argument("--set-id", help="Alma USER set ID")
    parser.add_argument("--tsv", help="TSV file with user IDs (one per line)")
    parser.add_argument("--pattern", help="Email pattern with {user_id} placeholder")
    parser.add_argument("--days", type=int, help="Days expired threshold")

    # Mode
    parser.add_argument("--live", action="store_true", help="Perform live update")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run (default)")

    # Optional settings
    parser.add_argument("--max-users", type=int, help="Maximum users to process (testing)")
    parser.add_argument("--batch-size", type=int, help="Batch size for processing")
    parser.add_argument("--output-dir", help="Output directory")

    args = parser.parse_args()

    # Handle sample config creation
    if args.create_sample_config:
        create_sample_config()
        return

    # Load configuration
    config = {}

    # Load from config file if specified
    if args.config:
        config = load_config_file(args.config)

    # Override with CLI args
    if args.environment:
        config['environment'] = args.environment
    if args.set_id:
        config['set_id'] = args.set_id
    if args.tsv:
        config['tsv_file'] = args.tsv
    if args.pattern:
        config['email_pattern'] = args.pattern
    if args.days:
        config['days_expired'] = args.days
    if args.live:
        config['dry_run'] = False
    elif args.dry_run:
        config['dry_run'] = True
    if args.max_users:
        config['max_users'] = args.max_users
    if args.batch_size:
        config['batch_size'] = args.batch_size
    if args.output_dir:
        config['output_dir'] = args.output_dir

    # Set defaults
    config.setdefault('environment', 'SANDBOX')
    config.setdefault('email_pattern', 'expired-{user_id}@institution.edu')
    config.setdefault('days_expired', 730)  # 2 years
    config.setdefault('dry_run', True)
    config.setdefault('batch_size', 50)
    config.setdefault('output_dir', './output')

    # Validate required parameters
    if not config.get('set_id') and not config.get('tsv_file'):
        print("Error: Either --set-id or --tsv must be specified")
        sys.exit(1)

    if config.get('set_id') and config.get('tsv_file'):
        print("Error: Cannot specify both --set-id and --tsv")
        sys.exit(1)

    # Validate email pattern
    valid_placeholders = ['{user_id}', '{first_name}', '{last_name}',
                         '{original_email}', '{original_local_part}', '{original_domain}']

    pattern = config['email_pattern']
    has_valid_placeholder = any(placeholder in pattern for placeholder in valid_placeholders)

    if not has_valid_placeholder:
        print(f"Error: Email pattern must contain at least one valid placeholder: {', '.join(valid_placeholders)}")
        sys.exit(1)

    # Validate allowed domains format
    if config.get('allowed_domains'):
        domains = config['allowed_domains']
        if not isinstance(domains, list):
            print("Error: allowed_domains must be a list")
            sys.exit(1)

        for domain in domains:
            if not isinstance(domain, str) or not domain.startswith('@'):
                print(f"Error: Domain '{domain}' must be a string starting with '@'")
                sys.exit(1)

    # Run the script
    try:
        script = EmailUpdateScript(config)
        success = script.run()
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\nScript interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
