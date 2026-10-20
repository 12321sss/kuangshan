package com.ganfeng.rs.audit;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AuditLogRepository extends JpaRepository<AuditLog, Long> {

    /** 最新 N 条（管理员看全量） */
    List<AuditLog> findAllByOrderByCreatedAtDesc(Pageable pageable);

    /** 按用户过滤（普通用户只看自己的操作） */
    List<AuditLog> findByUsernameOrderByCreatedAtDesc(String username, Pageable pageable);
}
