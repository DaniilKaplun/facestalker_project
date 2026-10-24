// YuNet (2023mar) output decoder for DeepStream nvinfer.
// Tensor layout and decoding: OpenCV FaceDetectorYN / face_detect.cpp.
// NMS and scaling back to the original frame are performed by nvinfer.
#include "nvdsinfer_custom_impl.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string>

extern "C" bool NvDsInferParseYuNet(
    std::vector<NvDsInferLayerInfo> const& layers,
    NvDsInferNetworkInfo const& network,
    NvDsInferParseDetectionParams const& params,
    std::vector<NvDsInferObjectDetectionInfo>& objects)
{
    if (params.numClassesConfigured != 1 || params.perClassPreclusterThreshold.empty())
        return false;
    auto find = [&](const std::string& name) -> const NvDsInferLayerInfo* {
        for (const auto& layer : layers)
            if (layer.layerName && name == layer.layerName) return &layer;
        return nullptr;
    };
    const float threshold = params.perClassPreclusterThreshold[0];
    for (const int stride : {8, 16, 32}) {
        const auto suffix = std::to_string(stride);
        const auto* cls = find("cls_" + suffix);
        const auto* obj = find("obj_" + suffix);
        const auto* box = find("bbox_" + suffix);
        const unsigned cols = network.width / stride;
        const unsigned rows = network.height / stride;
        const unsigned count = cols * rows;
        if (!cls || !obj || !box || !cls->buffer || !obj->buffer || !box->buffer ||
            cls->dataType != FLOAT || obj->dataType != FLOAT || box->dataType != FLOAT ||
            cls->inferDims.numElements != count || obj->inferDims.numElements != count ||
            box->inferDims.numElements != count * 4) {
            std::cerr << "Invalid YuNet output tensors for stride " << stride << std::endl;
            return false;
        }
        const auto* classes = static_cast<const float*>(cls->buffer);
        const auto* confidence = static_cast<const float*>(obj->buffer);
        const auto* boxes = static_cast<const float*>(box->buffer);
        for (unsigned i = 0; i < count; ++i) {
            const float score = std::sqrt(std::clamp(classes[i], 0.f, 1.f) *
                                          std::clamp(confidence[i], 0.f, 1.f));
            if (!std::isfinite(score) || score < threshold) continue;
            const float cx = (i % cols + boxes[i * 4]) * stride;
            const float cy = (i / cols + boxes[i * 4 + 1]) * stride;
            const float w = std::exp(boxes[i * 4 + 2]) * stride;
            const float h = std::exp(boxes[i * 4 + 3]) * stride;
            if (!std::isfinite(cx) || !std::isfinite(cy) ||
                !std::isfinite(w) || !std::isfinite(h)) continue;
            const float left = std::clamp(cx - w / 2, 0.f, float(network.width));
            const float top = std::clamp(cy - h / 2, 0.f, float(network.height));
            const float right = std::clamp(cx + w / 2, 0.f, float(network.width));
            const float bottom = std::clamp(cy + h / 2, 0.f, float(network.height));
            if (right <= left || bottom <= top) continue;
            NvDsInferObjectDetectionInfo face{};
            face.classId = 0;
            face.left = left;
            face.top = top;
            face.width = right - left;
            face.height = bottom - top;
            face.detectionConfidence = score;
            objects.push_back(face);
        }
    }
    return true;
}

CHECK_CUSTOM_PARSE_FUNC_PROTOTYPE(NvDsInferParseYuNet);
