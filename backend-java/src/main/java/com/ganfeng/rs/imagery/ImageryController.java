package com.ganfeng.rs.imagery;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 影像库控制器
 *
 * 两条解译路线的统一入口：
 * - 上传高分影像：POST /api/imagery/upload（坐标系由用户选择）
 * - 公开数据检索：GET /api/imagery/scenes/search（转发 inference 的 Sentinel-2 检索）
 * - 登记公开场景：POST /api/imagery/register-public（检索结果入库后可开始提取）
 */
@RestController
@RequestMapping("/api/imagery")
public class ImageryController {

    private final ImageryService service;
    private final PermissionGuard guard;

    /** inference 服务地址（注意：本机 8000 被占用，实际跑 8010） */
    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    public ImageryController(ImageryService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    /** 管理员可跨项目访问；其他角色受项目成员清单约束 */
    private boolean isAdmin(Authentication auth) {
        return guard.roleCodesOf(auth).contains("ADMIN");
    }

    @GetMapping
    public ApiResponse<List<Imagery>> list(@RequestParam(required = false) Long projectId,
                                          @RequestParam(required = false) String source,
                                          Authentication auth) {
        return ApiResponse.ok(service.list(projectId, source, auth.getName(), isAdmin(auth)));
    }

    @GetMapping("/{id}")
    public ApiResponse<Imagery> get(@PathVariable long id, Authentication auth) {
        return ApiResponse.ok(service.get(id, auth.getName(), isAdmin(auth)));
    }

    /** 可选坐标系列表（上传时前端下拉） */
    @GetMapping("/crs-options")
    public ApiResponse<List<ImageryService.CoordinateSystem>> crsOptions() {
        return ApiResponse.ok(ImageryService.CRS_OPTIONS);
    }

    /**
     * 上传高分影像（multipart/form-data）
     * 坐标系由用户选择，crs 参数必填；bounds 为 WGS84 覆盖范围（前端地图绘制）
     */
    @PostMapping("/upload")
    public ApiResponse<Imagery> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam Long projectId,
            @RequestParam(required = false) String name,
            @RequestParam String crs,
            @RequestParam LocalDate acquisitionDate,
            @RequestParam(required = false) Double resolutionM,
            @RequestParam List<Double> bounds,
            Authentication auth) {
        guard.require(auth, "action:imagery-manage");
        // 只能往自己可见的项目里传影像
        guard.requireAccess(projectId, auth.getName(), isAdmin(auth));
        return ApiResponse.ok(service.upload(file, projectId, name, crs,
                acquisitionDate, resolutionM, bounds));
    }

    /**
     * 检索 Sentinel-2 公开场景（在线提取的数据源）。
     * 直接转发 inference，避免前端跨域与暴露外部地址。
     */
    @GetMapping("/scenes/search")
    public ApiResponse<Object> searchScenes(
            @RequestParam double lng,
            @RequestParam double lat,
            @RequestParam String start,
            @RequestParam String end,
            @RequestParam(defaultValue = "15") double maxCloud,
            @RequestParam(defaultValue = "20") int limit,
            @RequestParam(defaultValue = "MSIL1C") String level) {
        String url = String.format(
                "%s/api/v1/scenes?lng=%s&lat=%s&start=%s&end=%s&maxCloud=%s&limit=%s&level=%s",
                inferenceBaseUrl, lng, lat, start, end, maxCloud, limit, level);
        try {
            String body = HttpJson.get(url);
            return ApiResponse.ok(HttpJson.extractData(body));
        } catch (Exception e) {
            throw new BizException(502, "公开数据源检索失败：" + e.getMessage());
        }
    }

    /** 登记一景公开数据（检索结果入库，之后可在影像库点选提取） */
    @PostMapping("/register-public")
    public ApiResponse<Imagery> registerPublic(@RequestBody RegisterPublicRequest req,
                                               Authentication auth) {
        guard.require(auth, "action:imagery-manage");
        if (req.projectId != null) {
            guard.requireAccess(req.projectId, auth.getName(), isAdmin(auth));
        }
        List<Double> b = req.bounds == null ? new ArrayList<>() : req.bounds;
        if (b.size() != 4) {
            throw BizException.badRequest("bounds 需为 [west, south, east, north]");
        }
        return ApiResponse.ok(service.registerPublic(
                req.projectId, req.name, req.source, req.productId,
                req.acquisitionDate, req.cloudCover,
                b.get(0), b.get(1), b.get(2), b.get(3),
                req.resolutionM == null ? 10.0 : req.resolutionM,
                req.note, req.filePath));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:imagery-manage");
        // 先校验访问权再删，避免越权删除他人项目影像
        service.get(id, auth.getName(), isAdmin(auth));
        service.delete(id);
        return ApiResponse.ok(null);
    }

    /** 切换收藏：客户星标常用影像，下次一键定位复用 */
    @PutMapping("/{id}/favorite")
    public ApiResponse<Imagery> toggleFavorite(@PathVariable long id,
                                               @RequestParam(required = false) Boolean value,
                                               Authentication auth) {
        Imagery img = service.get(id, auth.getName(), isAdmin(auth));
        // 未显式传值时取反（前端点星即切换）
        boolean target = value != null ? value : !Boolean.TRUE.equals(img.getFavorite());
        img.setFavorite(target);
        return ApiResponse.ok(service.save(img));
    }

    /** 供解译服务回查影像的本地绝对路径 */
    @GetMapping("/{id}/path")
    public ApiResponse<Map<String, Object>> resolvePath(@PathVariable long id, Authentication auth) {
        Imagery img = service.get(id, auth.getName(), isAdmin(auth));
        return ApiResponse.ok(Map.of(
                "id", img.getId(),
                "path", service.resolvePath(img),
                "source", img.getSource()));
    }

    public record RegisterPublicRequest(
            Long projectId,
            String name,
            String source,
            String productId,
            LocalDate acquisitionDate,
            Double cloudCover,
            Double resolutionM,
            List<Double> bounds,
            String note,
            /** 可选：公开数据下载到本地缓存后的绝对路径，回填后可直接解译 */
            String filePath
    ) {}

    /** 极简 HTTP + JSON 工具（demo 期不引额外依赖） */
    static final class HttpJson {
        private static final java.net.http.HttpClient CLIENT =
                java.net.http.HttpClient.newBuilder()
                        .connectTimeout(java.time.Duration.ofSeconds(10)).build();

        static String get(String url) throws Exception {
            var req = java.net.http.HttpRequest.newBuilder(java.net.URI.create(url))
                    .header("Accept", "application/json")
                    .timeout(java.time.Duration.ofSeconds(60))
                    .GET().build();
            var resp = CLIENT.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() / 100 != 2) {
                throw new IllegalStateException("HTTP " + resp.statusCode());
            }
            return resp.body();
        }

        /** 从 {"code":0,"data":[...]} 中抽出 data */
        @SuppressWarnings("unchecked")
        static Object extractData(String body) {
            try {
                var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
                var node = mapper.readTree(body);
                var data = node.get("data");
                return mapper.convertValue(data, Object.class);
            } catch (Exception e) {
                throw new IllegalStateException("响应解析失败: " + e.getMessage());
            }
        }
    }
}