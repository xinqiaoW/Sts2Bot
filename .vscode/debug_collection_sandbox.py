"""Run one simulator collection pass in a private, resumable debug directory."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    if len(sys.argv) != 1:
        raise SystemExit('这个调试入口不接受参数；配置模拟器请使用 STS2_SIMULATOR_BUNDLE')
    from tools.collect_simulator import main
    main(['--directory', str(ROOT / '.local/debug-simulator'), '--limit', '1'])
