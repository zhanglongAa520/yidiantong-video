"""可插拔支付提供方。

启用方式：环境变量 PAYMENT_PROVIDERS=mock,wechat,alipay（逗号分隔，按需启用）。
- mock    ：本地测试用，点击即“支付成功”。**切勿在公网生产环境启用**。
- wechat  ：微信支付 V3 Native 扫码支付 —— 仅为骨架，需商户资质与证书后补全签名/验签实现。
- alipay  ：支付宝 电脑网站/当面付 —— 仅为骨架，需开放平台应用与密钥后补全签名/验签实现。

所有提供方实现同一接口：
    configured() -> bool                     是否已配置齐全，可展示给用户
    create(order: dict, base_url) -> dict    创建支付，返回 {"type": "redirect"|"qrcode"|"mock", "url": ...}
    verify_notify(body: bytes, headers) -> (order_id, trade_no)   校验异步通知，成功返回订单号
"""
import os

class Provider:
    id = ""; name = ""
    required_env: list = []
    def configured(self):
        return all(os.getenv(k) for k in self.required_env)
    def create(self, order, base_url):
        raise NotImplementedError
    def verify_notify(self, body, headers):
        raise NotImplementedError

class MockProvider(Provider):
    id, name = "mock", "模拟支付（测试）"
    def configured(self): return True
    def create(self, order, base_url):
        return {"type": "mock", "url": f"/api/pay/mock/{order['id']}/complete"}

class WechatPayProvider(Provider):
    """微信支付 APIv3 Native 下单：POST https://api.mch.weixin.qq.com/v3/pay/transactions/native
    需要：商户号 WECHAT_MCHID、关联 AppID WECHAT_APPID、APIv3 密钥 WECHAT_API_V3_KEY、
    商户 API 证书序列号 WECHAT_CERT_SERIAL、商户私钥文件 WECHAT_PRIVATE_KEY_PATH、回调地址 WECHAT_NOTIFY_URL（必须 HTTPS 公网可达）。
    """
    id, name = "wechat", "微信支付"
    required_env = ["WECHAT_MCHID", "WECHAT_APPID", "WECHAT_API_V3_KEY", "WECHAT_CERT_SERIAL", "WECHAT_PRIVATE_KEY_PATH", "WECHAT_NOTIFY_URL"]
    def create(self, order, base_url):
        body = {  # 请求体结构（供实现参考）
            "appid": os.getenv("WECHAT_APPID"), "mchid": os.getenv("WECHAT_MCHID"),
            "description": order["plan_name"], "out_trade_no": order["id"],
            "notify_url": os.getenv("WECHAT_NOTIFY_URL"), "amount": {"total": order["amount_cents"], "currency": "CNY"},
        }
        # TODO: 用商户私钥对 "POST\n/v3/pay/transactions/native\n{ts}\n{nonce}\n{json}\n" 做 SHA256-RSA 签名，
        #       放入 Authorization: WECHATPAY2-SHA256-RSA2048 头；响应中的 code_url 生成二维码返回 {"type":"qrcode","url":code_url}
        raise NotImplementedError("微信支付尚未接入：需要商户号与 API 证书，并补全 payments.WechatPayProvider 的签名实现")
    def verify_notify(self, body, headers):
        # TODO: 用微信支付平台证书验证 Wechatpay-Signature，再用 APIv3 密钥 AES-256-GCM 解密 resource，
        #       trade_state == "SUCCESS" 时返回 (out_trade_no, transaction_id)
        raise NotImplementedError("微信支付回调验签未实现")

class AlipayProvider(Provider):
    """支付宝 alipay.trade.page.pay（电脑网站）/ alipay.trade.precreate（当面付扫码）。
    需要：ALIPAY_APP_ID、应用私钥 ALIPAY_PRIVATE_KEY_PATH、支付宝公钥 ALIPAY_PUBLIC_KEY_PATH、
    回调地址 ALIPAY_NOTIFY_URL，网关 ALIPAY_GATEWAY（默认 https://openapi.alipay.com/gateway.do，沙箱可改为 openapi-sandbox）。
    """
    id, name = "alipay", "支付宝"
    required_env = ["ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY_PATH", "ALIPAY_PUBLIC_KEY_PATH", "ALIPAY_NOTIFY_URL"]
    def create(self, order, base_url):
        biz = {"out_trade_no": order["id"], "total_amount": f"{order['amount_cents'] / 100:.2f}",
               "subject": order["plan_name"], "product_code": "FAST_INSTANT_TRADE_PAY"}
        # TODO: 组装公共参数(app_id, method, charset, sign_type=RSA2, timestamp, version, notify_url, biz_content)，
        #       按 key 排序拼接后用应用私钥 RSA2 签名，返回 {"type":"redirect","url": gateway + "?" + query}
        raise NotImplementedError("支付宝尚未接入：需要开放平台应用与密钥，并补全 payments.AlipayProvider 的签名实现")
    def verify_notify(self, body, headers):
        # TODO: 解析表单，去掉 sign/sign_type 后排序拼接，用支付宝公钥 RSA2 验签；
        #       trade_status in (TRADE_SUCCESS, TRADE_FINISHED) 时返回 (out_trade_no, trade_no)，并响应纯文本 "success"
        raise NotImplementedError("支付宝回调验签未实现")

ALL = {p.id: p for p in (MockProvider(), WechatPayProvider(), AlipayProvider())}

def enabled():
    ids = [x.strip() for x in os.getenv("PAYMENT_PROVIDERS", "").split(",") if x.strip()]
    return [ALL[i] for i in ids if i in ALL]

def get(pid):
    for p in enabled():
        if p.id == pid: return p
    return None
