package com.ganfeng.rs.notification;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 通知服务：查询 / 发通知 / 标记已读。
 *
 * 发通知的调用方是后台任务完成点（形变回调、告警触发等），
 * 这里只负责落库，推送（WebSocket/轮询）由前端轮询未读数驱动——demo 期
 * 用轮询足够，避免引入 WebSocket 的会话管理复杂度。
 */
@Service
public class NotificationService {

    private final NotificationRepository repo;

    public NotificationService(NotificationRepository repo) {
        this.repo = repo;
    }

    @Transactional
    public List<Notification> list(String userId) {
        return repo.findByUserIdOrderByCreatedAtDesc(userId);
    }

    @Transactional
    public long unreadCount(String userId) {
        return repo.countByUserIdAndReadFalse(userId);
    }

    @Transactional
    public Notification markRead(Long id, String userId) {
        Notification n = repo.findById(id)
                .orElseThrow(() -> new BizException(404, "通知不存在"));
        if (!n.getUserId().equals(userId)) {
            throw new BizException(403, "无权操作他人通知");
        }
        n.setRead(true);
        return repo.save(n);
    }

    @Transactional
    public Notification notify(String userId, String title, String content,
                              String type, String link) {
        return repo.save(new Notification(userId, title, content, type, link));
    }
}
