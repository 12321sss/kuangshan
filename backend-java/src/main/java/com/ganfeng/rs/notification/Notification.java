package com.ganfeng.rs.notification;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 站内通知（notifications 表）。
 *
 * 产生来源：形变分析任务完成 / 告警触发 / 其它后台任务完成。
 * 前端在顶栏铃铛处展示未读通知，点击后按 link 跳转并标记已读。
 *
 * type：DEFORMATION（形变分析）/ ALARM（告警）/ SYSTEM（系统）
 * link：跳转路径（如 /deformation），前端点击通知后跳回对应页面
 */
@Entity
@Table(name = "notifications")
public class Notification {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 接收人用户名（当前只做单人，不做广播） */
    @Column(nullable = false, length = 64)
    private String userId;

    @Column(nullable = false, length = 128)
    private String title;

    @Column(columnDefinition = "TEXT")
    private String content;

    @Column(nullable = false, length = 32)
    private String type = "SYSTEM";

    @Column(length = 256)
    private String link;

    @Column(name = "is_read", nullable = false)
    private Boolean read = false;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    protected Notification() {}

    public Notification(String userId, String title, String content, String type, String link) {
        this.userId = userId;
        this.title = title;
        this.content = content;
        this.type = type;
        this.link = link;
    }

    public Long getId() { return id; }
    public String getUserId() { return userId; }
    public String getTitle() { return title; }
    public String getContent() { return content; }
    public String getType() { return type; }
    public String getLink() { return link; }
    public Boolean getRead() { return read; }
    public LocalDateTime getCreatedAt() { return createdAt; }

    public void setRead(Boolean read) { this.read = read; }
}
