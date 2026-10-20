package com.ganfeng.rs.task;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 解译任务控制器（**流水追溯用**）
 *
 * 变更：原本是独立页面入口，现已整合进影像库/解译工作台，本控制器仅供
 * 查询与删除（报告追溯用）。创建入口改为 record()，状态由 inference 回调驱动。
 */
@RestController
@RequestMapping("/api/tasks")
public class TaskController {

    private final TaskService taskService;
    private final PermissionGuard guard;

    public TaskController(TaskService taskService, PermissionGuard guard) {
        this.taskService = taskService;
        this.guard = guard;
    }

    /** 创建任务请求体 */
    public record CreateTaskRequest(
            @NotBlank(message = "任务名称不能为空") String name,
            @NotNull(message = "项目不能为空") Long projectId,
            @NotBlank(message = "算法类型不能为空") String algoType,
            String imageName
    ) {}

    @GetMapping
    public ApiResponse<List<InterpretTask>> list(@RequestParam(required = false) Long projectId) {
        return ApiResponse.ok(taskService.list(projectId));
    }

    @GetMapping("/{id}")
    public ApiResponse<InterpretTask> get(@PathVariable long id) {
        return ApiResponse.ok(taskService.get(id));
    }

    @PostMapping
    public ApiResponse<InterpretTask> create(@Valid @RequestBody CreateTaskRequest req,
                                             Authentication auth) {
        guard.require(auth, "action:extract-manage");
        return ApiResponse.ok(taskService.record(req.name(), req.projectId(), req.algoType(), req.imageName()));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        taskService.delete(id);
        return ApiResponse.ok(null);
    }
}
