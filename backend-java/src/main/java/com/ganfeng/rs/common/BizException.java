package com.ganfeng.rs.common;

/**
 * 类型化业务异常：code 直接决定 HTTP 状态码，message 为对客户端友好的文案
 * 绝不在 message 中携带堆栈或内部细节
 */
public class BizException extends RuntimeException {

    private final int code;

    public BizException(int code, String message) {
        super(message);
        this.code = code;
    }

    public int getCode() {
        return code;
    }

    public static BizException badRequest(String msg) {
        return new BizException(400, msg);
    }

    public static BizException unauthorized(String msg) {
        return new BizException(401, msg);
    }

    public static BizException notFound(String msg) {
        return new BizException(404, msg);
    }
}
