package com.ganfeng.rs.common;

/**
 * 统一响应包装：{ code, message, data }
 * code = 0 成功；非 0 为业务/系统错误码
 */
public record ApiResponse<T>(int code, String message, T data) {

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(0, "success", data);
    }

    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null);
    }
}
