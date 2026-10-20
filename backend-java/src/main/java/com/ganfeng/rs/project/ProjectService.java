package com.ganfeng.rs.project;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 项目服务（MySQL 持久化）
 * 数据授权规则：管理员可见全部项目；其他角色只能看到成员清单里包含自己的项目
 */
@Service
public class ProjectService {

    private final ProjectRepository repo;

    public ProjectService(ProjectRepository repo) {
        this.repo = repo;
    }

    @Transactional(readOnly = true)
    public List<Project> listForUser(String username, boolean isAdmin) {
        List<Project> all = repo.findAllByOrderByIdAsc();
        // members 是 LAZY 集合，open-in-view 关闭时必须在事务内触网加载，否则序列化抛 LazyInitializationException
        all.forEach(p -> p.getMembers().size());
        if (isAdmin) {
            return all;
        }
        return all.stream().filter(p -> p.getMembers().contains(username)).toList();
    }

    @Transactional(readOnly = true)
    public Project get(long id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("项目不存在: " + id));
    }

    /** 校验当前用户是否有权访问某项目的数据 */
    @Transactional(readOnly = true)
    public void requireAccess(long projectId, String username, boolean isAdmin) {
        if (isAdmin) return;
        Project p = get(projectId);
        if (!p.getMembers().contains(username)) {
            throw new BizException(403, "你不在该项目的成员清单中，无权查看");
        }
    }

    @Transactional
    public Project create(Project req) {
        return repo.save(req);
    }

    @Transactional
    public Project update(long id, Project req) {
        Project p = get(id);
        p.setName(req.getName());
        p.setRegion(req.getRegion());
        p.setStatus(req.getStatus());
        p.setManager(req.getManager());
        p.setDescription(req.getDescription());
        return repo.save(p);
    }

    @Transactional
    public void delete(long id) {
        get(id);
        repo.deleteById(id);
    }

    @Transactional
    public Project setMembers(long id, List<String> members) {
        Project p = get(id);
        p.setMembers(members == null ? List.of() : members);
        return repo.save(p);
    }
}
