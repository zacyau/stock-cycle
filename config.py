"""全局配置：默认标的、牛熊参数、指标卡片定义、配色常量。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

# ---------------------------------------------------------------- 数据源
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
    "Accept": "*/*",
}
# 单次请求最多返回的 K 线根数（实测约 640）
PAGE_SIZE = 640
# 分段抓取时每段跨越的年数
SEGMENT_YEARS = 2
# 遇 WAF 拦截时的重试次数
MAX_RETRIES = 5
# 抓取起点（腾讯最早数据约为 2010 年，实际以标的上市日为准）
EARLIEST_DATE = "2004-01-01"
# 缓存有效期（小时）：超过则自动增量更新
CACHE_TTL_HOURS = 6
# 拼接连续性阈值：相邻收盘价跳变超过该比例则告警并重抓该段
CONTINUITY_JUMP = 0.35

# ---------------------------------------------------------------- 标的
DEFAULT_CODE = "sh510500"
CODE_PRESETS = [
    ("sh510500", "中证500ETF 南方"),
    ("sh000905", "中证500 指数"),
    ("sh510300", "沪深300ETF 华泰柏瑞"),
    ("sh000300", "沪深300 指数"),
    ("sz159915", "创业板ETF 易方达"),
    ("sh000001", "上证指数"),
    ("sh513100", "纳指ETF 国泰"),
    ("sh518880", "黄金ETF 华安"),
]

# ---------------------------------------------------------------- 牛熊摆动法参数
SWING_THRESHOLDS = [15, 20, 25]      # 百分比，页面可切换
DEFAULT_THRESHOLD = 20
FREQUENCIES = ["month", "day"]        # 月线（对齐参考图二口径）/ 日线
DEFAULT_FREQUENCY = "month"

# ---------------------------------------------------------------- 多时间尺度统计卡片
# kind: window = 固定日历窗口回溯；ytd = 年初至今；ath = 距离历史前高；since = 自定义基准日
PERIOD_CARDS = [
    {"key": "w1",     "label": "1周",              "kind": "window", "days": 7},
    {"key": "m1",     "label": "1月",              "kind": "window", "days": 30},
    {"key": "m3",     "label": "3月",              "kind": "window", "days": 91},
    {"key": "m6",     "label": "6月",              "kind": "window", "days": 182},
    {"key": "ytd",    "label": "年初至今",          "kind": "ytd"},
    {"key": "ath",    "label": "距离前高",          "kind": "ath"},
    {"key": "y1",     "label": "1年",              "kind": "window", "days": 365},
    {"key": "since",  "label": "自成立以来",          "kind": "since",  "default": ""},
    {"key": "y3",     "label": "3年",              "kind": "window", "days": 1095},
    {"key": "y5",     "label": "5年",              "kind": "window", "days": 1825},
]

# ---------------------------------------------------------------- 视觉
COLORS = {
    "nav": "#2b7fd4",        # 净值曲线（蓝）
    "nav_fill": "rgba(43,127,212,0.10)",
    "dd": "#3fae6a",         # 回撤 / 熊市（绿，A股跌色）
    "dd_fill": "rgba(63,174,106,0.16)",
    "bull": "#e8544f",       # 牛市 / 上涨（红，A股涨色）
    "bull_fill": "rgba(232,84,79,0.14)",
    "bear_band": "rgba(151,196,168,0.34)",
    "bear_band_pending": "rgba(151,196,168,0.16)",
    "grid": "#e8ecf1",
    "text": "#1f2937",
    "text_sub": "#6b7280",
}
