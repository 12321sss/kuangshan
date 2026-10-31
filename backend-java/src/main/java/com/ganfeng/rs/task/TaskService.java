package com.ganfeng.rs.task;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 解译任务服务（**已降级为流水追溯，不再有模拟器**）
 *
 * 变更说明：
 * - 原实现有「按创建时长 20 秒自动推进到 SUCCESS」的模拟器，
 *   那是在掩盖「后端从不真正调用 inference」的事实，已随真实链路打通而删除
 * - 现在任务的真实状态由 inference 回调驱动（见InferenceCallbackController）
 * - 本类只保留查询与删除，供报告与问题追溯使用；
 *   前端已不再有独立的任务页（已整合进影像库/解译工作台）
 */
@Service
public class TaskService {

    private final TaskRepository repo;

    public TaskService(TaskRepository repo) {
        this.repo = repo;
    }

    @Transactional
    public List<InterpretTask> list(Long projectId) {
        return projectId == null
                ? repo.findAll()
                : repo.findByProjectIdOrderByCreatedAtDesc(projectId);
    }

    @Transactional
    public InterpretTask get(long id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("任务不存在: " + id));
    }

    /** 登记一条任务流水（真实解译提交时调用），状态由后续回调更新 */
    @Transactional
    public InterpretTask record(String name, Long projectId, String algoType, String imageName) {
        InterpretTask t = new InterpretTask(name, projectId, algoType, "PENDING", 0,
                imageName, LocalDateTime.now());
        return repo.save(t);
    }

    /** 更新任务状态（回调驱动）。 */
    @Transactional
    public InterpretTask updateStatus(long id, String status, int progress) {
        InterpretTask t = repo.findById(id)
                .orElseThrow(() -> BizException.notFound("任务不存在: " + id));
        t.setStatus(status);
        t.setProgress(progress);
        return repo.save(t);
    }

    @Transactional
    public void delete(long id) {
        repo.findById(id).orElseThrow(() -> BizException.notFound("任务不存在: " + id));
        repo.deleteById(id);
    }
}