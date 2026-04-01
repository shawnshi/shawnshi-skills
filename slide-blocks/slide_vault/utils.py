# -*- coding: utf-8 -*-
"""
utils.py - SlideBlocks 公共工具函数
"""
import time

def with_retry(max_retries=3, base_delay=2):
    """指数退避自动重试装饰器，应对 API 限流与网络波动"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    err_msg = str(e).lower()
                    if "429" in err_msg or "quota" in err_msg or "ssl" in err_msg or "eof" in err_msg or "failed_precondition" in err_msg:
                        print(f"    [Retry] 遇到网络/限流错误，{delay}秒后重试... ({attempt+1}/{max_retries})")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        raise e
        return wrapper
    return decorator
