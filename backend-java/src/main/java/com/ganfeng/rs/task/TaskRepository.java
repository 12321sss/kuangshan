package com.ganfeng.rs.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface TaskRepository extends JpaRepository<InterpretTask, Long> {

    List<InterpretTask> findByProjectIdOrderByCreatedAtDesc(Long projectId);
}
