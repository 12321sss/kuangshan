"""验证阿里云 AccessKey（用官方 SDK，签名交给 SDK 处理）。

实测教训：手写阿里云 RPC 签名容易踩Timestamp 双重编码的坑
（冒号需%253A），官方 SDK 已处理妥当，不要自己实现。

用法：python probe_aliyun.py <AccessKeyId> <AccessKeySecret>
"""
import json
import sys

from aliyunsdkcore import client
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdksts.request.v20150401.GetCallerIdentityRequest import GetCallerIdentityRequest


def parse(raw):
    if isinstance(raw, bytes):
        return json.loads(raw.decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def verify(ak: str, sk: str) -> dict | None:
    cl = client.AcsClient(ak, sk, "cn-hangzhou")
    try:
        return parse(cl.do_action_with_exception(GetCallerIdentityRequest()))
    except ServerException as e:
        print(f"[FAIL] 服务端拒绝 status={e.status_code}")
        print(f"  code: {e.get_error_code()}")
        print(f"  msg : {str(e.get_error_message())[:200]}")
    except ClientException as e:
        print(f"[FAIL] 客户端/签名错误 code={e.get_error_code()}")
        print(f"  msg : {str(e.get_error_message())[:200]}")
    return None


def check_aiearth() -> None:
    print("\n=== AI Earth 数知地球站点可达性 ===")
    import urllib.error
    import urllib.request
    for url in ("https://engine-aiearth.aliyun.com/",
                "https://engine-aiearth.aliyun.com/api/v1/health"):
        host = url.split("//")[1][:44]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rs-platform/0.1"})
            with urllib.request.urlopen(req, timeout=20) as r:
                print(f"  {host:46s} HTTP {r.status_code}")
        except urllib.error.HTTPError as e:
            print(f"  {host:46s} HTTP {e.code}（端点可达）")
        except Exception as e:  # noqa: BLE001
            print(f"  {host:46s} {type(e).__name__}")


def main() -> bool:
    if len(sys.argv) < 3:
        print("用法：python probe_aliyun.py <AccessKeyId> <AccessKeySecret>")
        sys.exit(1)
    ak, sk = sys.argv[1], sys.argv[2]

    print("=== 验证 AccessKey（STS GetCallerIdentity）===")
    info = verify(ak, sk)
    if not info:
        return False

    print("[PASS] 凭证有效")
    print(f"  IdentityType : {info.get('IdentityType')}")
    print(f"  Arn          : {info.get('Arn')}")
    print(f"  AccountId    : {info.get('AccountId')}")

    if info.get("IdentityType") == "RAMUser":
        print("  [提示] RAM 子账号凭证（比主账号安全，推荐）")
    else:
        print("  [注意] 非 RAM 子账号，建议改用子账号并只授最小权限")

    check_aiearth()
    return True


if __name__ == "__main__":
    if main():
        print("\n=== 凭证可用。下一步（需人工操作）===")
        print("  1. 浏览器登录 https://engine-aiearth.aliyun.com/（该阿里云账号）")
        print("  2. 确认 AI Earth 已开通")
        print("  3. 数据检索里搜 Sentinel-2，确认能否**下载原始波段**")
        print("     （L2A / L1C 各试一次，记录文件格式与单文件大小）")
        print("  4. 把结论告诉我，我按实际方式接入")
        print("\n  [安全] 该 AccessKey 已在对话中明文出现，"
              "测完请在控制台禁用并重新生成")