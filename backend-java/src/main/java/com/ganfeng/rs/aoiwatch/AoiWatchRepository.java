package com.ganfeng.rs.aoiwatch;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AoiWatchRepository extends JpaRepository<AoiWatch, Long> {

    List<AoiWatch> findByProjectIdOrderByIdDesc(Long projectId);

    List<AoiWatch> findByProjectIdAndUsernameOrderByIdDesc(Long projectId, String username);
}
