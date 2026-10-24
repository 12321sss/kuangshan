package com.ganfeng.rs.project;

import com.ganfeng.rs.auth.UserRepository;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.role.Role;
import com.ganfeng.rs.role.RoleStore;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 项目服务（MySQL 持久化）
 *
 * 数据授权规则（2026-10-24 补充角色级项目范围）：
 *   管理员 → 全部项目
 *   其他   → 角色配置的可见项目（ALL / SPECIFIC / NONE） **∪** 个人成员关系
 *
 * 为什么要有角色级：原先项目可见性只靠 project_members，
 * 新建角色/用户登录后一个项目都看不到，必须逐个去「项目管理 → 成员」添加，极易漏配。
 * 现在角色上可以直接指定可见项目，新用户自动生效；个人成员仍可额外补充（取并集不覆盖）。
 */
@Service
public class ProjectService {

    private final ProjectRepository repo;
    private final UserRepository userRepo;
    private final RoleStore roleStore;

    public ProjectService(ProjectRepository repo, UserRepository userRepo, RoleStore roleStore) {
        this.repo = repo;
        this.userRepo = userRepo;
        this.roleStore = roleStore;
    }

    /** 角色级项目范围快照：all=true 表示全部；否则看 ids 集合 */
    private record ProjectScope(boolean all, Set<Long> ids) {
        static ProjectScope empty() { return new ProjectScope(false, Set.of()); }
    }

    /** 按用户名解析其角色配置的项目范围（查不到角色/异常时退化为「无额外范围」） */
    private ProjectScope resolveScope(String username) {
        if (username == null || username.isBlank()) return ProjectScope.empty();
        try {
            return userRepo.findByUsername(username)
                    .map(u -> roleStore.get(u.getRole()))
                    .map(r -> toScope(r))
                    .orElse(ProjectScope.empty());
        } catch (Exception e) {
            // 角色被删或数据异常时不影响主流程，退化为仅按个人成员
            return ProjectScope.empty();
        }
    }

    private static ProjectScope toScope(Role r) {
        // 管理员角色恒为全部，不依赖 DB 里的配置（双保险）
        if ("ADMIN".equals(r.getCode())) {
            return new ProjectScope(true, Set.of());
        }
        String scope = r.getProjectScope();
        if ("ALL".equalsIgnoreCase(scope)) {
            return new ProjectScope(true, Set.of());
        }
        if ("SPECIFIC".equalsIgnoreCase(scope)) {
            Set<Long> ids = new HashSet<>();
            for (String s : r.getProjectIds()) {
                try {
                    ids.add(Long.parseLong(s.trim()));
                } catch (NumberFormatException ignore) {
                    // 脏数据跳过，不阻断
                }
            }
            return new ProjectScope(false, ids);
        }
        return ProjectScope.empty();
    }

    @Transactional(readOnly = true)
    public List<Project> listForUser(String username, boolean isAdmin) {
        List<Project> all = repo.findAllByOrderByIdAsc();
        // members 是 LAZY 集合，open-in-view 关闭时必须在事务内触网加载，否则序列化抛 LazyInitializationException
        all.forEach(p -> p.getMembers().size());
        if (isAdmin) {
            return all;
        }
        ProjectScope scope = resolveScope(username);
        if (scope.all()) {
            return all;
        }
        return all.stream().filter(p -> canSee(p, username, scope)).toList();
    }

    /** 角色范围 ∪ 个人成员，任一命中即可见 */
    private static boolean canSee(Project p, String username, ProjectScope scope) {
        if (scope.ids().contains(p.getId())) return true;
        return p.getMembers().contains(username);
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
        // 与 listForUser 保持同一套判定：角色范围 ∪ 个人成员清单
        ProjectScope scope = resolveScope(username);
        if (scope.all() || canSee(p, username, scope)) {
            return;
        }
        throw new BizException(403, "你不在该项目的授权范围内，无权查看");
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
