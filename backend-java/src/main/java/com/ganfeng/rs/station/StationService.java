package com.ganfeng.rs.station;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 站点服务（MySQL 持久化，支持增删改查）
 */
@Service
public class StationService {

    private final StationRepository repo;

    public StationService(StationRepository repo) {
        this.repo = repo;
    }

    public List<Station> list(Long projectId) {
        return projectId == null ? repo.findAll() : repo.findByProjectIdOrderByIdAsc(projectId);
    }

    public Station get(String id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("站点不存在: " + id));
    }

    @Transactional
    public Station create(Station req) {
        if (req.getId() == null || req.getId().isBlank()) {
            throw BizException.badRequest("站点编号不能为空");
        }
        if (repo.existsById(req.getId())) {
            throw BizException.badRequest("站点编号已存在: " + req.getId());
        }
        return repo.save(req);
    }

    @Transactional
    public Station update(String id, Station req) {
        Station existing = get(id);
        req.setId(id); // id 不可改
        repo.delete(existing);
        return repo.save(req);
    }

    @Transactional
    public void delete(String id) {
        get(id);
        repo.deleteById(id);
    }
}
