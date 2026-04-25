# services.py
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from typing import List, Dict, Any, Optional
import uuid

from .models import ValidationRun, ValidationIssue, RecordSummary
from .validators import ValidationEngine, DictionaryLoader


class DataQualityService:
    """Main service orchestration"""

    def validate_project_data(
            self,
            project,
            data_records: List[Dict[str, Any]],
            field_schemas: Dict[str, Any],
            triggered_by=None
    ) -> ValidationRun:
        """Validate project data and save results using ORM directly"""

        # Create validation run
        run = ValidationRun.objects.create(
            run_id=str(uuid.uuid4())[:8],
            project=project,
            triggered_by=triggered_by,
            status='running'
        )

        try:
            # Run validation
            engine = ValidationEngine(field_schemas)
            results = engine.validate_records(data_records)

            # Save results using bulk operations
            with transaction.atomic():
                issues_to_create = []

                for result in results:
                    # Update record summary
                    summary, _ = RecordSummary.objects.get_or_create(
                        project=project,
                        record_id=result['record_id']
                    )

                    # Create issues
                    for issue_data in result['issues']:
                        issues_to_create.append(ValidationIssue(
                            project=project,
                            validation_run=run,
                            record_id=result['record_id'],
                            field_name=issue_data['field_name'],
                            severity=issue_data['severity'],
                            rule_name=issue_data['rule_name'],
                            message=issue_data['message'],
                            actual_value=str(issue_data.get('actual_value', ''))[:500],
                            expected_value=issue_data.get('expected_value', '')[:500],
                            assigned_to=triggered_by if issue_data['severity'] == 'error' else None,
                        ))

                    # Update summary
                    summary.error_count = result['error_count']
                    summary.warning_count = result['warning_count']
                    summary.has_errors = result['error_count'] > 0
                    summary.is_valid = result['is_valid']
                    summary.save()

                # Bulk create issues for performance
                if issues_to_create:
                    ValidationIssue.objects.bulk_create(issues_to_create)

            # Update run statistics
            run.total_records = len(results)
            run.records_with_errors = sum(1 for r in results if not r['is_valid'])
            run.total_errors = sum(r['error_count'] for r in results)
            run.total_warnings = sum(r['warning_count'] for r in results)
            run.status = 'completed'
            run.completed_at = timezone.now()
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
            run.save()

            return run

        except Exception as e:
            run.status = 'failed'
            run.error_log = str(e)
            run.save()
            raise


class IssueService:
    """Issue management using Django ORM"""

    def get_issues(self, project, filters=None, page=1, per_page=50):
        """Get paginated issues with filters"""
        queryset = ValidationIssue.objects.filter(project=project).select_related('assigned_to')

        if filters:
            if filters.get('status'):
                queryset = queryset.filter(status=filters['status'])
            if filters.get('severity'):
                queryset = queryset.filter(severity=filters['severity'])
            if filters.get('assigned_to_me') and filters.get('user'):
                queryset = queryset.filter(assigned_to=filters['user'])
            if filters.get('record_id'):
                queryset = queryset.filter(record_id=filters['record_id'])

        paginator = Paginator(queryset, per_page)
        return paginator.get_page(page)

    def get_issue_summary(self, project):
        """Get summary statistics using ORM aggregation"""
        from django.db.models import Count, Q

        issues = ValidationIssue.objects.filter(project=project, status__in=['open', 'in_review'])

        return {
            'total_issues': issues.count(),
            'errors': issues.filter(severity='error').count(),
            'warnings': issues.filter(severity='warning').count(),
            'by_field': list(issues.values('field_name').annotate(count=Count('id')).order_by('-count')[:10]),
            'by_rule': list(issues.values('rule_name').annotate(count=Count('id')).order_by('-count')),
            'unresolved_for_7days': issues.filter(created_at__lte=timezone.now() - timezone.timedelta(days=7)).count(),
        }

    def resolve_issue(self, issue_id, user, note=''):
        """Resolve a single issue"""
        try:
            issue = ValidationIssue.objects.get(id=issue_id)
            issue.resolve(user, note)

            # Refresh record summary
            summary = RecordSummary.objects.get(project=issue.project, record_id=issue.record_id)
            summary.refresh()

            return True
        except ValidationIssue.DoesNotExist:
            return False

    def assign_issues(self, issue_ids, user):
        """Assign issues to a user"""
        updated = ValidationIssue.objects.filter(id__in=issue_ids).update(assigned_to=user)
        return updated

    def get_record_issues(self, project, record_id):
        """Get all issues for a specific record"""
        return ValidationIssue.objects.filter(
            project=project,
            record_id=record_id
        ).select_related('assigned_to').order_by('severity', 'field_name')