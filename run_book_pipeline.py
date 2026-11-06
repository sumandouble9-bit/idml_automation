"""Run the book pipeline (formatting -> normalize -> image injection -> export).

Input for this step is the vertical_bottom_align output (Output/vertical_bottom_align), produced first by
`python vertical_bottom_align.py`. The vertical-align step itself is NOT run here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from book_workflow.paths import WorkflowPaths
from book_workflow.workflow import BookWorkflow, build_arg_parser


def main(argv=None):
    """Discover the bottom-aligned IDMLs and run formatting through export."""
    args, _unknown = build_arg_parser().parse_known_args(argv)
    language = None if args.lang == "all" else args.lang

    paths = WorkflowPaths()
    paths.input_dir = paths.workflow_dir / "idml_input_files"
    if not paths.input_dir.is_dir() or not any(paths.input_dir.glob("*.idml")):
        print(f"No IDML files found in {paths.input_dir}.")
        return

    BookWorkflow(paths).run(
        book=args.book or args.book_pos,
        language=language,
        step=args.step,
        limit=args.limit,
        force=args.force,
    )


if __name__ == "__main__":
    main()
