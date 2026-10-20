package com.ganfeng.rs.audit;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 操作日志（audit_logs 表）：记录关键操作，供管理员审计追溯。
 *
 * 记录范围：登录/登出、提交解译、保存解译结果、删除实体、权限变更。
 * 只追加不修改，不提供修改接口（审计日志被篡改就失去意义）。
 */
@Entity
@Table(name = "audit_logs", indexes = {
        @Index(name = "idx_audit_created", columnList = "createdAt"),
        @Index(name = "idx_audit_user", columnList = "username")
})
public class AuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(length = 64)
    private String username;

    /** LOGIN / LOGOUT / EXTRACT_SAVE / EXTRACT_SUBMIT / DELETE / UPDATE_PERM */
    @Column(nullable = false, length = 32)
    private String action;

    /** 操作对象类型：AUTH / EXTRACTION / IMAGERY / PROJECT / ROLE / ALARM */
    @Column(length = 32)
    private String entityType;

    /** 操作对象标识（id 或名称） */
    @Column(length = 128)
    private String entityRef;

    /** 操作描述（人类可读） */
    @Column(length = 512)
    private String detail;

    @Column(length = 64)
    private String ip;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    protected AuditLog() {}

    public AuditLog(String username, String action, String entityType, String entityRef,
                    String detail, String ip) {
        this.username = username;
        this.action = action;
        this.entityType = entityType;
        this.entityRef = entityRef;
        this.detail = detail;
        this.ip = ip;
        this.createdAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public String getUsername() { return username; }
    public String getAction() { return action; }
    public String getEntityType() { return entityType; }
    public String getEntityRef() { return entityRef; }
    public String getDetail() { return detail; }
    public String getIp() { return ip; }
    public LocalDateTime getCreatedAt() { return createdAt; }
}
