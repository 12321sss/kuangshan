package com.ganfeng.rs.audit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 审计日志服务：写日志永不抛异常（审计失败不能影响业务主流程）。
 */
@Service
public class AuditLogService {

    private static final Logger log = LoggerFactory.getLogger(AuditLogService.class);

    private final AuditLogRepository repo;

    public AuditLogService(AuditLogRepository repo) {
        this.repo = repo;
    }

    /** 记录一条操作日志；任何异常只打 warn，不向上抛 */
    public void record(String username, String action, String entityType, String entityRef,
                       String detail, String ip) {
        try {
            repo.save(new AuditLog(username, action, entityType, entityRef, detail, ip));
        } catch (Exception e) {
            log.warn("审计日志写入失败 action={} user={}: {}", action, username, e.getMessage());
        }
    }

    public List<AuditLog> list(String username, boolean isAdmin, int limit) {
        PageRequest page = PageRequest.of(0, Math.min(Math.max(limit, 1), 500));
        return isAdmin
                ? repo.findAllByOrderByCreatedAtDesc(page)
                : repo.findByUsernameOrderByCreatedAtDesc(username, page);
    }
}
