"""终端颜色工具"""


class Colors:
    """终端颜色代码"""
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    @classmethod
    def disable(cls):
        """禁用颜色输出"""
        for attr in ['RESET', 'RED', 'GREEN', 'YELLOW', 'BLUE',
                     'MAGENTA', 'CYAN', 'WHITE', 'BOLD', 'DIM']:
            setattr(cls, attr, '')