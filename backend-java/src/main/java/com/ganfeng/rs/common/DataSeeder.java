package com.ganfeng.rs.common;

import com.ganfeng.rs.auth.UserAccount;
import com.ganfeng.rs.auth.UserRepository;
import com.ganfeng.rs.role.PermCatalog;
import com.ganfeng.rs.role.Role;
import com.ganfeng.rs.role.RoleRepository;
import com.ganfeng.rs.warning.WarningRule;
import com.ganfeng.rs.warning.WarningRuleRepository;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 数据初始化器：首次启动（空库）时写入「系统基础数据」。
 *
 * 只建三类系统运行必需的基础数据：
 *   1. 角色 + 权限（没有角色就没人能登录、权限体系无法运转）
 *   2. 管理员账号 admin（唯一的初始登录入口）
 *   3. 预警规则出厂默认值（用户只能改不能新建，删了就没规则可用）
 *
 * 不再播种演示业务数据（示例项目/传感器/站点/任务/告警）。
 * 之前这些假数据会让客户生产库里躺着一批不存在的站点和告警，
 * 交付后还要逐条删；项目/传感器/告警一律由客户通过页面真实录入。
 */
@Component
public class DataSeeder implements ApplicationRunner {

    private final UserRepository userRepo;
    private final RoleRepository roleRepo;
    private final WarningRuleRepository ruleRepo;
    private final PasswordEncoder passwordEncoder;

    public DataSeeder(UserRepository userRepo, RoleRepository roleRepo,
                      WarningRuleRepository ruleRepo, PasswordEncoder passwordEncoder) {
        this.userRepo = userRepo;
        this.roleRepo = roleRepo;
        this.ruleRepo = ruleRepo;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        if (roleRepo.count() > 0) {
            return; // 非空库不初始化，避免覆盖用户数据
        }
        seedRoles();
        seedUsers();
        seedRules();
    }

    private void seedRoles() {
        roleRepo.save(new Role("ADMIN", "系统管理员", "全部权限",
                PermCatalog.PAGES.stream().map(p -> p.get("code")).toList(),
                PermCatalog.ACTIONS.stream().map(a -> a.get("code")).toList(), true));
        roleRepo.save(new Role("MANAGER", "项目管理员", "项目管理、预警配置、告警确认、站点与影像管理",
                List.of("page:dashboard", "page:monitor", "page:warning-rules", "page:warning-alarms",
                        "page:ops-stations", "page:analysis", "page:extract", "page:imagery",
                        "page:projects", "page:screen"),
                List.of("action:rule-edit", "action:alarm-ack", "action:station-manage",
                        "action:project-manage", "action:imagery-manage", "action:extract-manage"), true));
        roleRepo.save(new Role("ANALYST", "解译分析师", "影像库、在线提取、告警确认",
                List.of("page:dashboard", "page:monitor", "page:warning-alarms", "page:ops-stations",
                        "page:analysis", "page:extract", "page:imagery", "page:screen"),
                List.of("action:alarm-ack", "action:imagery-manage", "action:extract-manage"), true));
        roleRepo.save(new Role("VIEWER", "观察员", "只读查看",
                List.of("page:dashboard", "page:monitor", "page:warning-alarms", "page:ops-stations",
                        "page:analysis", "page:screen"),
                List.of(), true));
    }

    private void seedUsers() {
        userRepo.save(new UserAccount("admin", "系统管理员", "ADMIN", "13800000001", "ENABLED",
                passwordEncoder.encode("admin123")));
    }

    private void seedRules() {
        // 预警规则出厂默认值：用户只能改阈值、不能新增规则类型，
        // 这里提供四类默认规则作为起点（位移/雨量/含水率/水位）
        ruleRepo.save(new WarningRule("DISP", "位移计", "合位移", "mm", 5.0, 10.0, 20.0, true));
        ruleRepo.save(new WarningRule("RAIN", "雨量站", "小时雨量", "mm/h", 20.0, 40.0, 60.0, true));
        ruleRepo.save(new WarningRule("SOIL", "土壤含水率", "体积含水率", "%", 30.0, 38.0, 45.0, true));
        ruleRepo.save(new WarningRule("WATER", "水位计", "水位", "m", 2.0, 3.0, 4.0, false));
    }
}
