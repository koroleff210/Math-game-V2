import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from app.services.ib_physics_importer import (  # noqa: E402
    apply_repair_imported_ib_physics_quality,
    audit_imported_ib_physics_quality,
    ImportValidationError,
    build_import_plan,
    filters_from_args,
    format_quality_audit_report,
    format_plan_report,
    format_repair_plan_report,
    parse_import_args,
    plan_repair_imported_ib_physics_quality,
    write_import_plan,
)


def main(argv: list[str] | None = None) -> int:
    args = parse_import_args(argv)
    dry_run = not args.write
    flask_app = create_app()
    with flask_app.app_context():
        try:
            if args.audit_imported_quality:
                audit = audit_imported_ib_physics_quality(
                    source_root=args.source_root,
                    question_bank=args.question_bank,
                )
                print(format_quality_audit_report(audit))
                return 0

            if args.repair_imported_quality:
                repair_plan = plan_repair_imported_ib_physics_quality(
                    source_root=args.source_root,
                    question_bank=args.question_bank,
                )
                print(format_repair_plan_report(repair_plan, dry_run=dry_run))
                if dry_run:
                    print('\nDry-run only: no imported problems were updated.')
                    return 0
                result = apply_repair_imported_ib_physics_quality(repair_plan)
                print('\nRepair completed.')
                print(f'Updated imported problems: {result["updated_count"]}')
                return 0

            plan = build_import_plan(
                source_root=args.source_root,
                question_bank=args.question_bank,
                filters=filters_from_args(args),
                static_root=flask_app.static_folder,
            )
            print(format_plan_report(plan, dry_run=dry_run))
            if dry_run:
                print('\nDry-run only: no database rows were created and no images were copied.')
                return 0

            result = write_import_plan(
                plan,
                library_only=args.library_only,
                subject_name=args.subject_name,
                topic_name=args.topic_name,
            )
            print('\nImport completed.')
            if args.library_only:
                print('ProblemSet id: none (library-only import)')
            else:
                print(f'ProblemSet id: {result["problem_set_id"]}')
            print(f'Problem ids: {", ".join(str(problem_id) for problem_id in result["problem_ids"])}')
            print(f'Import batch id: {result["import_batch_id"]}')
            print(f'Copied images: {len(result["copied_images"])}')
            return 0
        except ImportValidationError as exc:
            print(f'Import validation failed: {exc}', file=sys.stderr)
            return 2


if __name__ == '__main__':
    raise SystemExit(main())
