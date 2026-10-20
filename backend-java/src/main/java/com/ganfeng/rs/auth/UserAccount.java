package com.ganfeng.rs.auth;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 用户账号实体（users 表）
 * passwordHash 标 @JsonIgnore，永不出现在接口返回中
 */
@Entity
@Table(name = "users")
public class UserAccount {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 64)
    private String username;

    @Column(nullable = false, length = 64)
    private String displayName;

    /** 绑定的角色编码（角色可在角色管理中自定义） */
    @Column(nullable = false, length = 32)
    private String role;

    @Column(length = 32)
    private String phone = "";

    /** ENABLED 启用 / DISABLED 禁用 */
    @Column(nullable = false, length = 16)
    private String status = "ENABLED";

    @JsonIgnore
    @Column(nullable = false)
    private String passwordHash;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    @Column(nullable = false)
    private LocalDateTime updatedAt = LocalDateTime.now();

    protected UserAccount() {}

    public UserAccount(String username, String displayName, String role, String phone,
                       String status, String passwordHash) {
        this.username = username;
        this.displayName = displayName;
        this.role = role;
        this.phone = phone;
        this.status = status;
        this.passwordHash = passwordHash;
    }

    @PreUpdate
    void touch() {
        this.updatedAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public String getUsername() { return username; }
    public String getDisplayName() { return displayName; }
    public String getRole() { return role; }
    public String getPhone() { return phone; }
    public String getStatus() { return status; }
    public String getPasswordHash() { return passwordHash; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }

    public void setDisplayName(String displayName) { this.displayName = displayName; }
    public void setRole(String role) { this.role = role; }
    public void setPhone(String phone) { this.phone = phone; }
    public void setStatus(String status) { this.status = status; }
    public void setPasswordHash(String passwordHash) { this.passwordHash = passwordHash; }
}
