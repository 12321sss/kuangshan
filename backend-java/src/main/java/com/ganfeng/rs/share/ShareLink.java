package com.ganfeng.rs.share;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 访客分享链接：客户可生成只读链接，把项目数据视图分享给未登录的第三方（领导/合作方）。
 *
 * 安全设计：
 * - token 为随机 32 位十六进制串，不可猜测
 * - 只读：只暴露项目概况与解译统计，不提供任何写操作
 * - 带过期时间（默认 7 天），过期即失效
 */
@Entity
@Table(name = "share_links", uniqueConstraints =
        @UniqueConstraint(name = "uk_share_token", columnNames = "token"))
public class ShareLink {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 64)
    private String token;

    @Column(nullable = false)
    private Long projectId;

    @Column(length = 64)
    private String createdBy;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    @Column(nullable = false)
    private LocalDateTime expiresAt;

    @Column(nullable = false)
    private Boolean revoked = false;

    protected ShareLink() {}

    public ShareLink(String token, Long projectId, String createdBy, int validDays) {
        this.token = token;
        this.projectId = projectId;
        this.createdBy = createdBy;
        this.createdAt = LocalDateTime.now();
        this.expiresAt = LocalDateTime.now().plusDays(validDays);
    }

    /** 是否仍可访问（未撤销且未过期） */
    public boolean isActive() {
        return !Boolean.TRUE.equals(revoked) && LocalDateTime.now().isBefore(expiresAt);
    }

    public Long getId() { return id; }
    public String getToken() { return token; }
    public Long getProjectId() { return projectId; }
    public String getCreatedBy() { return createdBy; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public LocalDateTime getExpiresAt() { return expiresAt; }
    public Boolean getRevoked() { return revoked; }

    public void setRevoked(Boolean revoked) { this.revoked = revoked; }
}
