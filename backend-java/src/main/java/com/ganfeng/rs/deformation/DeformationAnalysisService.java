package com.ganfeng.rs.deformation;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 形变分析结果的业务逻辑。
 *
 * 职责：CRUD + 软删除 + 项目隔离校验（隔离在 Controller 的 PermissionGuard 做，
 * 本层只负责数据读写，不校验权限——与其它 Service 的分层一致）。
 */
@Service
public class DeformationAnalysisService {

    private final DeformationAnalysisRepository repo;

    public DeformationAnalysisService(DeformationAnalysisRepository repo) {
        this.repo = repo;
    }

    /** 项目内未删除的分析（列表页） */
    public List<DeformationAnalysis> list(Long projectId) {
        return repo.findByProjectIdAndDeletedFalseOrderByCreatedAtDesc(projectId);
    }

    /** 项目内全部（含软删除，供回收站） */
    public List<DeformationAnalysis> listAll(Long projectId) {
        return repo.findByProjectIdOrderByCreatedAtDesc(projectId);
    }

    /** 单条查询（校验存在性） */
    public DeformationAnalysis get(Long id) {
        return repo.findById(id)
                .orElseThrow(() -> BizException.notFound("形变分析不存在: " + id));
    }

    @Transactional
    public DeformationAnalysis create(DeformationAnalysis entity) {
        entity.setId(null);
        entity.setDeleted(false);
        return repo.save(entity);
    }

    /** 软删除（进回收站，不物理删） */
    @Transactional
    public void softDelete(Long id, String username) {
        DeformationAnalysis d = get(id);
        d.setDeleted(true);
        d.setDeletedAt(java.time.LocalDateTime.now());
        d.setDeletedBy(username);
        repo.save(d);
    }

    /** 回收站恢复 */
    @Transactional
    public void restore(Long id) {
        DeformationAnalysis d = get(id);
        d.setDeleted(false);
        d.setDeletedAt(null);
        d.setDeletedBy(null);
        repo.save(d);
    }

    /** 物理删除（回收站里彻底删，含速率场文件） */
    @Transactional
    public void purge(Long id) {
        DeformationAnalysis d = get(id);
        if (d.getVelocityTifPath() != null) {
            try {
                java.nio.file.Files.deleteIfExists(java.nio.file.Paths.get(d.getVelocityTifPath()));
            } catch (java.io.IOException e) {
                // 文件删除失败不阻断记录删除，只记日志
                org.slf4j.LoggerFactory.getLogger(getClass())
                        .warn("删除速率场文件失败: {}", d.getVelocityTifPath(), e);
            }
        }
        repo.delete(d);
    }
}
