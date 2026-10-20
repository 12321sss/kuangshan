package com.ganfeng.rs.common;

import com.ganfeng.rs.alarm.Alarm;
import com.ganfeng.rs.alarm.AlarmRepository;
import com.ganfeng.rs.auth.UserAccount;
import com.ganfeng.rs.auth.UserRepository;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectRepository;
import com.ganfeng.rs.role.PermCatalog;
import com.ganfeng.rs.role.Role;
import com.ganfeng.rs.role.RoleRepository;
import com.ganfeng.rs.sensor.Sensor;
import com.ganfeng.rs.sensor.SensorRepository;
import com.ganfeng.rs.station.Station;
import com.ganfeng.rs.station.StationRepository;
import com.ganfeng.rs.task.InterpretTask;
import com.ganfeng.rs.task.TaskRepository;
import com.ganfeng.rs.warning.WarningRule;
import com.ganfeng.rs.warning.WarningRuleRepository;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 数据种子器：首次启动（空库）时写入演示数据
 * 只播种一次；之后所有数据通过页面 CRUD 维护
 */
@Component
public class DataSeeder implements ApplicationRunner {

    private final UserRepository userRepo;
    private final RoleRepository roleRepo;
    private final ProjectRepository projectRepo;
    private final SensorRepository sensorRepo;
    private final StationRepository stationRepo;
    private final TaskRepository taskRepo;
    private final AlarmRepository alarmRepo;
    private final WarningRuleRepository ruleRepo;
    private final PasswordEncoder passwordEncoder;

    public DataSeeder(UserRepository userRepo, RoleRepository roleRepo, ProjectRepository projectRepo,
                      SensorRepository sensorRepo, StationRepository stationRepo, TaskRepository taskRepo,
                      AlarmRepository alarmRepo, WarningRuleRepository ruleRepo,
                      PasswordEncoder passwordEncoder) {
        this.userRepo = userRepo;
        this.roleRepo = roleRepo;
        this.projectRepo = projectRepo;
        this.sensorRepo = sensorRepo;
        this.stationRepo = stationRepo;
        this.taskRepo = taskRepo;
        this.alarmRepo = alarmRepo;
        this.ruleRepo = ruleRepo;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        if (roleRepo.count() > 0) {
            return; // 非空库不播种
        }
        seedRoles();
        seedUsers();
        seedProjects();
        seedSensorsAndStations();
        seedTasks();
        seedAlarms();
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
        userRepo.save(new UserAccount("admin", "系统管理员", "ADMIN", "13800000001", "ENABLED", passwordEncoder.encode("admin123")));
        userRepo.save(new UserAccount("manager", "项目管理员", "MANAGER", "13800000002", "ENABLED", passwordEncoder.encode("manager123")));
        userRepo.save(new UserAccount("analyst", "解译分析师", "ANALYST", "13800000003", "ENABLED", passwordEncoder.encode("analyst123")));
        userRepo.save(new UserAccount("viewer", "观察员", "VIEWER", "13800000004", "ENABLED", passwordEncoder.encode("viewer123")));
    }

    private void seedProjects() {
        Project p1 = new Project("宁都河源锂矿遥感监测", "中国江西赣州", "RUNNING", "项目管理员",
                "国内条件样区：丘陵林地背景下的矿山地物与生态扰动监测");
        p1.setMembers(List.of("manager", "analyst", "viewer"));
        // 合规边界（demo 演示用，示意三个图层；生产期从矿权审批文件导入）
        // 矿权红线 > 实际扰动边界 > 生态红线（三者在空间上应大致同心或部分重叠）
        p1.setBoundaryJson("""
                {"mining":[[116.008,26.462],[116.034,26.462],[116.034,26.484],[116.008,26.484],[116.008,26.462]],\
                "disturbance":[[116.014,26.466],[116.028,26.466],[116.028,26.478],[116.014,26.478],[116.014,26.466]],\
                "ecological":[[116.030,26.470],[116.040,26.470],[116.040,26.486],[116.030,26.486],[116.030,26.470]]}\
                """);
        projectRepo.save(p1);

        Project p2 = new Project("Mount Marion 矿区时序监测", "澳大利亚西澳州", "RUNNING", "项目管理员",
                "成熟运营矿区：2016 年开采至今的长期时序、采坑推进与排土场变化");
        p2.setMembers(List.of("manager", "analyst"));
        projectRepo.save(p2);

        Project p3 = new Project("Pilgangoora 矿区对照监测", "澳大利亚西澳州", "RUNNING", "项目管理员",
                "对照样区：2018 年投产的成熟硬岩锂矿（参股项目，注意表述口径）");
        p3.setMembers(List.of("manager"));
        projectRepo.save(p3);

        Project p4 = new Project("Goulamina 矿区建设期监测", "马里", "PLANNING", "项目管理员",
                "建设/投产阶段样区：2025 年投产，侧重矿区扩张与植被扰动");
        p4.setMembers(List.of("manager"));
        projectRepo.save(p4);
    }

    private void seedSensorsAndStations() {
        // ---- 项目 1：宁都河源（8 台）----
        saveSensor("DISP-01", 1, "采坑东缘位移计", "DISP", 116.0212, 26.4741, "ONLINE", 2.31, "mm");
        saveSensor("DISP-02", 1, "采坑南缘位移计", "DISP", 116.0187, 26.4690, "ONLINE", 1.87, "mm");
        saveSensor("DISP-03", 1, "排土场北坡位移计", "DISP", 116.0250, 26.4802, "ALARM", 8.64, "mm");
        saveSensor("RAIN-01", 1, "矿区雨量站", "RAIN", 116.0198, 26.4725, "ONLINE", 12.4, "mm/h");
        saveSensor("SOIL-01", 1, "排土场土壤含水率", "SOIL", 116.0244, 26.4789, "ONLINE", 23.5, "%");
        saveSensor("SOIL-02", 1, "尾矿设施下游土壤", "SOIL", 116.0160, 26.4668, "OFFLINE", 0, "%");
        saveSensor("WATER-01", 1, "沉淀池水位计", "WATER", 116.0205, 26.4710, "ONLINE", 1.42, "m");
        saveSensor("WATER-02", 1, "排水沟水位计", "WATER", 116.0233, 26.4758, "ONLINE", 0.86, "m");
        // ---- 项目 2：Mount Marion（3 台）----
        saveSensor("DISP-11", 2, "North Pit 位移计", "DISP", 121.6208, -28.7901, "ONLINE", 1.24, "mm");
        saveSensor("DISP-12", 2, "Waste Dump 位移计", "DISP", 121.6280, -28.7855, "ONLINE", 2.02, "mm");
        saveSensor("RAIN-11", 2, "矿区雨量站", "RAIN", 121.6230, -28.7880, "ONLINE", 3.1, "mm/h");

        String region1 = "江西省赣州市宁都县";
        saveStation("S01", 1, "761", region1, "采坑东缘监测点01", "GNSS 地表位移监测站", "NORMAL", "17150057", "MS451L", "V1.0.1", "DISP-01");
        saveStation("S02", 1, "761", region1, "采坑南缘监测点02", "GNSS 地表位移监测站", "NORMAL", "17150262", "MS451L", "V1.0.1", "DISP-02");
        saveStation("S03", 1, "761", region1, "排土场北坡监测点03", "GNSS 地表位移监测站", "ABNORMAL", "17150214", "MS451L", "V1.0.1", "DISP-03");
        saveStation("S04", 1, "761", region1, "矿区雨量站", "一体化雨量监测站", "NORMAL", "17150512", "YL-200", "V2.3.0", "RAIN-01");
        saveStation("S05", 1, "761", region1, "排土场含水率站", "土壤含水率监测站", "NORMAL", "17150601", "SM-100", "V1.4.2", "SOIL-01");
        saveStation("S06", 1, "761", region1, "尾矿下游含水率站", "土壤含水率监测站", "MAINTAIN", "17150602", "SM-100", "V1.4.2", "SOIL-02");
        saveStation("S07", 1, "761", region1, "沉淀池水位站", "水位监测站", "NORMAL", "17150711", "SW-300", "V1.1.0", "WATER-01");
        saveStation("S08", 1, "761", region1, "排水沟水位站", "水位监测站", "NORMAL", "17150712", "SW-300", "V1.1.0", "WATER-02");
        saveStation("S11", 2, "MM-01", "澳大利亚西澳州", "North Pit 监测点", "GNSS 地表位移监测站", "NORMAL", "17160101", "MS451L", "V1.0.1", "DISP-11");
        saveStation("S12", 2, "MM-01", "澳大利亚西澳州", "Waste Dump 监测点", "GNSS 地表位移监测站", "NORMAL", "17160102", "MS451L", "V1.0.1", "DISP-12");
        saveStation("S13", 2, "MM-01", "澳大利亚西澳州", "雨量监测站", "一体化雨量监测站", "NORMAL", "17160103", "YL-200", "V2.3.0", "RAIN-11");
    }

    private void seedTasks() {
        taskRepo.save(new InterpretTask("宁都河源 2026-09 Sentinel-2 七类分割", 1L,
                "SEGMENTATION", "SUCCESS", 100, "S2A_20260915_NDHY.tif", LocalDateTime.of(2026, 10, 10, 9, 30)));
        taskRepo.save(new InterpretTask("Mount Marion 2026 Q3 NDVI 指数计算", 2L,
                "INDEX", "SUCCESS", 100, "S2B_20260922_MM.tif", LocalDateTime.of(2026, 10, 12, 16, 40)));
        taskRepo.save(new InterpretTask("Pilgangoora 2026-08 七类分割", 3L,
                "SEGMENTATION", "FAILED", 38, "S2A_20260830_PIL.tif", LocalDateTime.of(2026, 10, 13, 11, 20)));
    }

    private void seedAlarms() {
        alarmRepo.save(new Alarm(1L, "DISP-03", "排土场北坡位移计", "RED", "合位移", 8.64, 5.0, "mm", "UNACK",
                LocalDateTime.now().minusMinutes(42)));
        alarmRepo.save(new Alarm(1L, "RAIN-01", "矿区雨量站", "ORANGE", "小时雨量", 32.6, 20.0, "mm/h", "ACKED",
                LocalDateTime.now().minusHours(3)));
        alarmRepo.save(new Alarm(1L, "DISP-03", "排土场北坡位移计", "YELLOW", "合位移", 5.8, 5.0, "mm", "RESOLVED",
                LocalDateTime.now().minusDays(1).minusHours(2)));
        alarmRepo.save(new Alarm(1L, "SOIL-01", "排土场土壤含水率", "YELLOW", "体积含水率", 31.2, 30.0, "%", "RESOLVED",
                LocalDateTime.now().minusDays(2)));
        alarmRepo.save(new Alarm(1L, "WATER-01", "沉淀池水位计", "BLUE", "水位", 1.9, 2.0, "m", "RESOLVED",
                LocalDateTime.now().minusDays(3).minusHours(5)));
        alarmRepo.save(new Alarm(2L, "DISP-12", "Waste Dump 位移计", "YELLOW", "合位移", 5.2, 5.0, "mm", "UNACK",
                LocalDateTime.now().minusHours(6)));
    }

    private void seedRules() {
        ruleRepo.save(new WarningRule("DISP", "位移计", "合位移", "mm", 5.0, 10.0, 20.0, true));
        ruleRepo.save(new WarningRule("RAIN", "雨量站", "小时雨量", "mm/h", 20.0, 40.0, 60.0, true));
        ruleRepo.save(new WarningRule("SOIL", "土壤含水率", "体积含水率", "%", 30.0, 38.0, 45.0, true));
        ruleRepo.save(new WarningRule("WATER", "水位计", "水位", "m", 2.0, 3.0, 4.0, false));
    }

    private void saveSensor(String id, long projectId, String name, String type, double lng, double lat,
                            String status, double value, String unit) {
        sensorRepo.save(new Sensor(id, projectId, name, type, lng, lat, status, value, unit));
    }

    private void saveStation(String id, long projectId, String projectNo, String region, String name,
                             String type, String workStatus, String sn, String model, String firmware,
                             String sensorId) {
        Station s = new Station();
        s.setId(id);
        s.setProjectId(projectId);
        s.setProjectNo(projectNo);
        s.setRegion(region);
        s.setStationName(name);
        s.setStationType(type);
        s.setWorkStatus(workStatus);
        s.setFirstMonitorAt("2026-04-30 11:00:00");
        s.setLastMonitorAt("2026-10-16 14:00:00");
        s.setDeviceSn(sn);
        s.setDeviceWorkStatus("正常");
        s.setDeviceModel(model);
        s.setFirmware(firmware);
        s.setSensorId(sensorId);
        stationRepo.save(s);
    }
}
