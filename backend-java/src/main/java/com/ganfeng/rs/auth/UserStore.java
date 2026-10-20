package com.ganfeng.rs.auth;

import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.role.RoleStore;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.Set;

/**
 * 用户服务（MySQL 持久化）
 * admin 内置账号：不可删除、不可降级、不可禁用，防止把系统锁死
 */
@Service
public class UserStore {

    private final UserRepository repo;
    private final PasswordEncoder passwordEncoder;
    private final RoleStore roleStore;

    public UserStore(UserRepository repo, PasswordEncoder passwordEncoder, RoleStore roleStore) {
        this.repo = repo;
        this.passwordEncoder = passwordEncoder;
        this.roleStore = roleStore;
    }

    public List<UserAccount> list() {
        return repo.findAll();
    }

    public Optional<UserAccount> findByUsername(String username) {
        return repo.findByUsername(username);
    }

    @Transactional
    public UserAccount create(String username, String displayName, String rawPassword,
                              String phone, String role) {
        if (repo.existsByUsername(username)) {
            throw BizException.badRequest("用户名已存在: " + username);
        }
        requireRoleExists(role);
        return repo.save(new UserAccount(username, displayName, role, phone, "ENABLED",
                passwordEncoder.encode(rawPassword)));
    }

    @Transactional
    public UserAccount update(String username, String displayName, String phone,
                              String role, String status, String newPassword) {
        UserAccount existing = repo.findByUsername(username)
                .orElseThrow(() -> BizException.notFound("用户不存在: " + username));
        if (!Set.of("ENABLED", "DISABLED").contains(status)) {
            throw BizException.badRequest("非法状态: " + status);
        }
        requireRoleExists(role);
        if ("admin".equals(username) && (!"ADMIN".equals(role) || !"ENABLED".equals(status))) {
            throw BizException.badRequest("内置管理员账号不允许降级或禁用");
        }
        existing.setDisplayName(displayName);
        existing.setPhone(phone);
        existing.setRole(role);
        existing.setStatus(status);
        if (newPassword != null && !newPassword.isBlank()) {
            existing.setPasswordHash(passwordEncoder.encode(newPassword));
        }
        return repo.save(existing);
    }

    @Transactional
    public void delete(String username) {
        UserAccount existing = repo.findByUsername(username)
                .orElseThrow(() -> BizException.notFound("用户不存在: " + username));
        if ("admin".equals(existing.getUsername())) {
            throw BizException.badRequest("内置管理员账号不允许删除");
        }
        repo.delete(existing);
    }

    private void requireRoleExists(String role) {
        if (!roleStore.exists(role)) {
            throw BizException.badRequest("角色不存在: " + role);
        }
    }
}
