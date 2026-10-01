"""더블클릭으로 콘솔 창 없이 FocusApp을 실행합니다 (.pyw는 pythonw.exe로 열림)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from focus_app.main import main  # noqa: E402

raise SystemExit(main())
