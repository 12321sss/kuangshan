package com.ganfeng.rs.notification;

import com.ganfeng.rs.common.ApiResponse;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 通知中心接口。
 *
 *   GET  /api/notifications             当前用户通知列表
 *   GET  /api/notifications/unread-count 未读数（顶栏铃铛轮询用）
 *   POST /api/notifications/{id}/read    标记已读
 */
@RestController
@RequestMapping("/api/notifications")
public class NotificationController {

    private final NotificationService service;

    public NotificationController(NotificationService service) {
        this.service = service;
    }

    @GetMapping
    public ApiResponse<List<Notification>> list(Authentication auth) {
        return ApiResponse.ok(service.list(auth.getName()));
    }

    @GetMapping("/unread-count")
    public ApiResponse<Map<String, Long>> unreadCount(Authentication auth) {
        return ApiResponse.ok(Map.of("count", service.unreadCount(auth.getName())));
    }

    @PostMapping("/{id}/read")
    public ApiResponse<Notification> markRead(@PathVariable Long id, Authentication auth) {
        return ApiResponse.ok(service.markRead(id, auth.getName()));
    }
}
