package com.ganfeng.rs.dict;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 数据字典：地物类型 / 告警级别 / 单位的集中管理。
 *
 * 首次访问时若表为空自动播种默认字典（已有库也能生效，不依赖 DataSeeder）。
 * 管理员可修改中文名与颜色，前端图层渲染与列表展示统一读这里。
 */
@RestController
@RequestMapping("/api/dict")
public class DictController {

    private final DictItemRepository repo;
    private final PermissionGuard guard;

    public DictController(DictItemRepository repo, PermissionGuard guard) {
        this.repo = repo;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<DictItem>> list(@RequestParam(required = false) String category) {
        seedIfEmpty();
        return ApiResponse.ok(category == null || category.isBlank()
                ? repo.findAllByOrderByCategoryAscSortOrderAsc()
                : repo.findByCategoryOrderBySortOrderAsc(category));
    }

    /** 管理员改字典项（中文名/颜色/排序） */
    public record UpdateReq(String label, String color, Integer sortOrder) {}

    @PutMapping("/{id}")
    public ApiResponse<DictItem> update(@PathVariable long id, @RequestBody UpdateReq req,
                                        Authentication auth) {
        guard.require(auth, "action:project-manage");
        DictItem item = repo.findById(id)
                .orElseThrow(() -> com.ganfeng.rs.common.BizException.notFound("字典项不存在: " + id));
        if (req.label() != null && !req.label().isBlank()) item.setLabel(req.label());
        if (req.color() != null && !req.color().isBlank()) item.setColor(req.color());
        if (req.sortOrder() != null) item.setSortOrder(req.sortOrder());
        return ApiResponse.ok(repo.save(item));
    }

    /** 表为空时播种默认字典（幂等） */
    private synchronized void seedIfEmpty() {
        if (repo.countByCategory("CLASS_TYPE") > 0) {
            return;
        }
        List<DictItem> defaults = List.of(
                new DictItem("CLASS_TYPE", "PIT", "采坑", "#ef4444", 1),
                new DictItem("CLASS_TYPE", "DUMP", "排土场", "#f59e0b", 2),
                new DictItem("CLASS_TYPE", "TAILINGS", "尾矿库", "#8b5cf6", 3),
                new DictItem("CLASS_TYPE", "BARE", "裸地扰动", "#a8a29e", 4),
                new DictItem("CLASS_TYPE", "VEGETATION", "植被", "#22c55e", 5),
                new DictItem("CLASS_TYPE", "WATER", "水体", "#3b82f6", 6),
                new DictItem("CLASS_TYPE", "ROAD", "道路设施", "#78716c", 7),
                new DictItem("CLASS_TYPE", "BUILDING", "建筑", "#f97316", 8),
                new DictItem("CLASS_TYPE", "MOUNTAIN", "山体", "#6b7280", 9),
                new DictItem("ALARM_LEVEL", "RED", "红色（紧急）", "#ef4444", 1),
                new DictItem("ALARM_LEVEL", "ORANGE", "橙色（重要）", "#f97316", 2),
                new DictItem("ALARM_LEVEL", "YELLOW", "黄色（一般）", "#eab308", 3),
                new DictItem("ALARM_LEVEL", "BLUE", "蓝色（提示）", "#3b82f6", 4),
                new DictItem("UNIT", "KM2", "平方千米 km²", null, 1),
                new DictItem("UNIT", "HA", "公顷 ha", null, 2),
                new DictItem("UNIT", "MM", "毫米 mm", null, 3)
        );
        repo.saveAll(defaults);
    }
}
