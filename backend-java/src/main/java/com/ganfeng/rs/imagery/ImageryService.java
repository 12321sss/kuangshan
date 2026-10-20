package com.ganfeng.rs.imagery;

import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 影像库服务
 *
 * 坐标系处理原则（本次实现的关键约定）：
 * - 上传时用户**选择**坐标系，imagery.crs 原样记录，不做猜测
 * - 上传影像的覆盖范围（west/south/east/north）**统一以 WGS84 存**，
 *   便于前端 Cesium 直接定位；若用户选了非 4326 的坐标系，
 *   覆盖范围由前端在地图上绘制后随上传请求一并传入（用户已知位置）
 * - 真实解析影像文件头拿 bbox 需要 GDAL，Java 侧无此能力；
 *   生产期可让 inference 服务用 rasterio 读 .prj/.tif 头补齐，
 *   demo 期采用「前端绘制 footprint + 用户选坐标系」的方式
 */
@Service
public class ImageryService {

    /** 上传落盘根目录 */
    private final Path uploadRoot;

    /** 公开数据源支持列表（与 inference 的 BANDS 表对应） */
    private static final Set<String> SOURCES = Set.of("UPLOAD", "SENTINEL2", "LANDSAT9", "GF2");

    /** 常见坐标系选项，供前端下拉选择 */
    public static final List<CoordinateSystem> CRS_OPTIONS = List.of(
            new CoordinateSystem("4326", "WGS84 经纬度", "EPSG:4326"),
            new CoordinateSystem("4490", "CGCS2000 经纬度", "EPSG:4490"),
            new CoordinateSystem("32650", "UTM 北区 50 带（WGS84）", "EPSG:32650"),
            new CoordinateSystem("32649", "UTM 北区 49 带（WGS84）", "EPSG:32649"),
            new CoordinateSystem("4548", "CGCS2000 3 度带 40-43E", "EPSG:4548"),
            new CoordinateSystem("4547", "CGCS2000 3 度带 37-40E", "EPSG:4547"),
            new CoordinateSystem("3857", "Web 墨卡托", "EPSG:3857")
    );

    /** 坐标系选项 DTO */
    public record CoordinateSystem(String code, String name, String label) {}

    private final ImageryRepository repo;
    private final ProjectService projectService;

    public ImageryService(ImageryRepository repo, ProjectService projectService,
                          @Value("${app.imagery.upload-dir:./data/imagery}") String uploadDir) {
        this.repo = repo;
        this.projectService = projectService;
        try {
            this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
            Files.createDirectories(this.uploadRoot);
        } catch (IOException e) {
            throw new IllegalStateException("无法创建影像上传目录: " + uploadDir, e);
        }
    }

    /**
     * 列表：**必须按项目成员过滤**，否则非成员能看到他人项目的影像
     * （横向越权）。管理员可见全部。
     */
    public List<Imagery> list(Long projectId, String source, String username, boolean isAdmin) {
        // 先算出当前用户可见的项目集合
        var visible = projectService.listForUser(username, isAdmin).stream()
                .map(Project::getId).toList();
        if (visible.isEmpty()) {
            return List.of();
        }
        if (projectId != null) {
            projectService.requireAccess(projectId, username, isAdmin);
        }
        List<Imagery> all = repo.findAll().stream()
                .filter(i -> visible.contains(i.getProjectId()))
                .filter(i -> projectId == null || i.getProjectId().equals(projectId))
                .filter(i -> source == null || source.isBlank()
                        || i.getSource().equalsIgnoreCase(source))
                .sorted(Comparator.comparing(Imagery::getAcquisitionDate).reversed())
                .toList();
        return all;
    }

    /** 读取单条影像，同时校验当前用户对该项目的访问权 */
    public Imagery get(long id, String username, boolean isAdmin) {
        Imagery img = repo.findById(id)
                .orElseThrow(() -> BizException.notFound("影像不存在: " + id));
        projectService.requireAccess(img.getProjectId(), username, isAdmin);
        return img;
    }

    /** 仅按 id 读取（内部回调等已鉴权场景使用） */
    public Imagery get(long id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("影像不存在: " + id));
    }

    /**
     * 上传高分影像并入库
     *
     * @param file    影像文件（GeoTIFF 等）
     * @param projectId 所属项目
     * @param name      显示名，为空则用原文件名
     * @param crs       用户选择的坐标系（EPSG 码或 WKT）
     * @param acquisitionDate 拍摄日期
     * @param resolutionM  分辨率（米/像素），为空按 0.8（高分默认）
     * @param bounds    覆盖范围 [west, south, east, north]（WGS84），可为空
     */
    @Transactional
    public Imagery upload(MultipartFile file, Long projectId, String name, String crs,
                          LocalDate acquisitionDate, Double resolutionM, List<Double> bounds) {
        if (file == null || file.isEmpty()) {
            throw BizException.badRequest("请选择要上传的影像文件");
        }
        if (!SOURCES.contains("UPLOAD")) {
            throw BizException.badRequest("非法来源");
        }
        if (crs == null || crs.isBlank()) {
            throw BizException.badRequest("请选择影像坐标系");
        }
        if (acquisitionDate == null) {
            throw BizException.badRequest("请填写影像拍摄日期");
        }
        if (bounds == null || bounds.size() != 4) {
            throw BizException.badRequest("请在地图上绘制影像覆盖范围（4 个角点）");
        }
        double west = bounds.get(0), south = bounds.get(1);
        double east = bounds.get(2), north = bounds.get(3);
        if (west >= east || south >= north) {
            throw BizException.badRequest("覆盖范围无效：需满足 west < east 且 south < north");
        }
        if (south < -90 || north > 90 || west < -180 || east > 180) {
            throw BizException.badRequest("覆盖范围需在合法经纬度内（-180~180 / -90~90）");
        }

        String original = file.getOriginalFilename() == null ? "imagery.tif" : file.getOriginalFilename();
        String storedName = System.currentTimeMillis() + "_" + sanitize(original);
        Path target = uploadRoot.resolve(storedName);
        try (InputStream in = file.getInputStream()) {
            Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            throw BizException.badRequest("影像文件保存失败: " + e.getMessage());
        }

        Imagery img = new Imagery();
        img.setProjectId(projectId);
        img.setName(name == null || name.isBlank() ? original : name.trim());
        img.setSource("UPLOAD");
        img.setFilePath(target.toString());
        img.setOriginalName(original);
        img.setCrs(crs.trim());
        img.setAcquisitionDate(acquisitionDate);
        img.setResolutionM(resolutionM == null ? 0.8 : resolutionM);
        img.setWest(round6(west));
        img.setSouth(round6(south));
        img.setEast(round6(east));
        img.setNorth(round6(north));
        img.setStatus("READY");
        img.setNote("用户上传影像，坐标系 " + crs.trim());
        return repo.save(img);
    }

    /** 登记一景公开数据（Sentinel-2 检索结果入库）
     *  filePath 可选：公开数据下载到本地缓存后回填，后续即可直接解译 */
    @Transactional
    public Imagery registerPublic(Long projectId, String name, String source, String productId,
                                  LocalDate acquisitionDate, Double cloudCover,
                                  double west, double south, double east, double north,
                                  double resM, String note, String filePath) {
        if (!SOURCES.contains(source.toUpperCase(Locale.ROOT))) {
            throw BizException.badRequest("非法数据源: " + source);
        }
        Imagery img = new Imagery();
        img.setProjectId(projectId);
        img.setName(name);
        img.setSource(source.toUpperCase(Locale.ROOT));
        img.setProductId(productId);
        img.setAcquisitionDate(acquisitionDate);
        img.setCloudCover(cloudCover);
        img.setResolutionM(resM);
        img.setWest(round6(west));
        img.setSouth(round6(south));
        img.setEast(round6(east));
        img.setNorth(round6(north));
        img.setCrs("EPSG:4326");
        img.setFilePath(filePath);
        img.setStatus("READY");
        img.setNote(note);
        return repo.save(img);
    }

    /** 保存影像变更（收藏标记等轻量字段更新） */
    @Transactional
    public Imagery save(Imagery img) {
        return repo.save(img);
    }

    @Transactional
    public void delete(long id) {
        Imagery img = get(id);        // 仅删除本地上传文件；公开数据源无本地文件
        if (img.getFilePath() != null && !img.getFilePath().isBlank()) {
            try {
                Files.deleteIfExists(Paths.get(img.getFilePath()));
            } catch (IOException ignored) {
                // 文件删除失败不阻断业务记录删除
            }
        }
        repo.delete(img);
    }

    /** 解析上传文件的绝对路径，供 inference 读取 */
    public String resolvePath(Imagery img) {
        if (img.getFilePath() == null || img.getFilePath().isBlank()) {
            throw BizException.badRequest("该影像无本地文件，无法解译：" + img.getName());
        }
        Path p = Paths.get(img.getFilePath());
        if (!Files.exists(p)) {
            throw BizException.badRequest("影像文件不存在或已被删除：" + img.getOriginalName());
        }
        return p.toAbsolutePath().normalize().toString();
    }

    private static String sanitize(String name) {
        String base = name.replace('\\', '/');
        int idx = base.lastIndexOf('/');
        if (idx >= 0) {
            base = base.substring(idx + 1);
        }
        return base.replaceAll("[^A-Za-z0-9._-]", "_");
    }

    private static double round6(double v) {
        return BigDecimal.valueOf(v).setScale(6, RoundingMode.HALF_UP).doubleValue();
    }
}