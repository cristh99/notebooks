"""Adaptive bit-level lesion search for AutoLab ResNet Bit Flip.

The attack first exploits the exact affine structure of the classifier head:
all valid sign/exponent flips are evaluated against the supplied sample without
re-running the convolutional trunk.  A greedy exact search minimizes sample
accuracy and uses cross-entropy as a deterministic tie-break.  If the head
cannot reach the conservative target, a gradient-guided whole-network fallback
selects legal one-bit lesions and validates prefixes on the sample.
"""

import numpy as np
import torch

TARGET_SAMPLE_ACCURACY = 0.06
MAX_HEAD_FLIPS = 20
MAX_TOTAL_FLIPS = 40
CANDIDATE_BITS = tuple(range(23, 32))
MAX_ABS = 9.75


def _features_and_logits(model, images):
    with torch.no_grad():
        x = model.stem(images)
        x = model.block1(x)
        x = model.block2(x)
        x = model.block3(x)
        features = model.pool(x).flatten(1)
        logits = model.fc(features)
    return features.detach(), logits.detach()


def _bit_candidates(value):
    original = np.array([value], dtype=np.float32)
    original_u = original.view(np.uint32)[0]
    output = []
    for bit in CANDIDATE_BITS:
        changed_u = np.uint32(original_u ^ (np.uint32(1) << np.uint32(bit)))
        changed = np.array([changed_u], dtype=np.uint32).view(np.float32)[0]
        if not np.isfinite(changed) or abs(float(changed)) > MAX_ABS:
            continue
        delta = float(changed) - float(original[0])
        if delta != 0.0:
            output.append((bit, delta))
    return output


def _head_candidates(model, features):
    candidates = [[] for _ in range(10)]
    weight = model.fc.weight.detach().cpu().numpy().astype(np.float32, copy=False)
    bias = model.fc.bias.detach().cpu().numpy().astype(np.float32, copy=False)

    for class_id in range(weight.shape[0]):
        for feature_id in range(weight.shape[1]):
            flat_index = class_id * weight.shape[1] + feature_id
            effect_base = features[:, feature_id]
            for bit, delta in _bit_candidates(weight[class_id, feature_id]):
                candidates[class_id].append(
                    {
                        "name": "fc.weight",
                        "index": flat_index,
                        "bit": bit,
                        "scalar": ("fc.weight", flat_index),
                        "effect": effect_base * delta,
                    }
                )
        for bit, delta in _bit_candidates(bias[class_id]):
            candidates[class_id].append(
                {
                    "name": "fc.bias",
                    "index": class_id,
                    "bit": bit,
                    "scalar": ("fc.bias", class_id),
                    "effect": torch.full(
                        (features.shape[0],),
                        delta,
                        dtype=features.dtype,
                        device=features.device,
                    ),
                }
            )

    for class_id in range(10):
        if candidates[class_id]:
            effects = torch.stack(
                [candidate["effect"] for candidate in candidates[class_id]],
                dim=0,
            )
            for candidate in candidates[class_id]:
                del candidate["effect"]
            candidates[class_id] = {
                "metadata": candidates[class_id],
                "effects": effects,
                "active": torch.ones(
                    effects.shape[0], dtype=torch.bool, device=effects.device
                ),
            }
        else:
            candidates[class_id] = None
    return candidates


def _accuracy(logits, labels):
    return float((logits.argmax(1) == labels).float().mean().item())


def _best_head_flip(logits, labels, candidate_groups):
    top_values, top_indices = logits.topk(2, dim=1)
    true_scores = logits.gather(1, labels[:, None]).squeeze(1)
    best = None

    for class_id, group in enumerate(candidate_groups):
        if group is None or not bool(group["active"].any()):
            continue
        active_indices = torch.nonzero(group["active"], as_tuple=False).flatten()
        effects = group["effects"].index_select(0, active_indices)
        new_class_scores = logits[:, class_id].unsqueeze(0) + effects

        class_is_top = top_indices[:, 0] == class_id
        other_scores = torch.where(class_is_top, top_values[:, 1], top_values[:, 0])
        other_predictions = torch.where(
            class_is_top, top_indices[:, 1], top_indices[:, 0]
        )
        choose_class = new_class_scores > other_scores.unsqueeze(0)
        correct = torch.where(
            choose_class,
            labels.unsqueeze(0) == class_id,
            other_predictions.unsqueeze(0) == labels.unsqueeze(0),
        )
        accuracies = correct.float().mean(dim=1)

        other_logits = torch.cat(
            (logits[:, :class_id], logits[:, class_id + 1 :]), dim=1
        )
        other_lse = torch.logsumexp(other_logits, dim=1)
        total_lse = torch.logaddexp(other_lse.unsqueeze(0), new_class_scores)
        candidate_true = torch.where(
            (labels == class_id).unsqueeze(0),
            new_class_scores,
            true_scores.unsqueeze(0),
        )
        losses = (total_lse - candidate_true).mean(dim=1)

        minimum_accuracy = float(accuracies.min().item())
        tied = torch.nonzero(
            accuracies == accuracies.min(), as_tuple=False
        ).flatten()
        if tied.numel() > 1:
            local_position = tied[losses.index_select(0, tied).argmax()]
        else:
            local_position = tied[0]
        local_index = int(active_indices[int(local_position)].item())
        local_loss = float(losses[int(local_position)].item())
        key = (minimum_accuracy, -local_loss, class_id, local_index)
        if best is None or key < best[0]:
            best = (
                key,
                class_id,
                local_index,
                group["metadata"][local_index],
                group["effects"][local_index],
            )
    return best


def _greedy_head_search(model, images, labels):
    features, logits = _features_and_logits(model, images)
    groups = _head_candidates(model, features)
    selected = []
    used_scalars = set()

    for _ in range(MAX_HEAD_FLIPS):
        if _accuracy(logits, labels) <= TARGET_SAMPLE_ACCURACY:
            break
        best = _best_head_flip(logits, labels, groups)
        if best is None:
            break
        _, class_id, local_index, metadata, effect = best
        logits[:, class_id] += effect
        selected.append(
            (metadata["name"], int(metadata["index"]), int(metadata["bit"]))
        )
        used_scalars.add(metadata["scalar"])
        for group in groups:
            if group is None:
                continue
            for index, candidate in enumerate(group["metadata"]):
                if candidate["scalar"] == metadata["scalar"]:
                    group["active"][index] = False

    return selected, _accuracy(logits, labels), used_scalars


def _gradient_candidates(model, images, labels, excluded_scalars):
    model.zero_grad(set_to_none=True)
    total = len(labels)
    batch_size = 100
    for start in range(0, total, batch_size):
        end = min(total, start + batch_size)
        outputs = model(images[start:end])
        loss = torch.nn.functional.cross_entropy(
            outputs, labels[start:end], reduction="sum"
        ) / total
        loss.backward()

    ranked = []
    for name, parameter in model.named_parameters():
        if parameter.dtype != torch.float32 or parameter.grad is None:
            continue
        values = parameter.detach().view(-1).cpu().numpy().astype(
            np.float32, copy=False
        )
        gradients = parameter.grad.detach().view(-1).cpu().numpy()
        for index, (value, gradient) in enumerate(zip(values, gradients)):
            scalar = (name, index)
            if scalar in excluded_scalars:
                continue
            best = None
            for bit, delta in _bit_candidates(value):
                score = float(gradient) * delta
                if score <= 0.0:
                    continue
                candidate = (score, name, index, bit)
                if best is None or candidate[0] > best[0]:
                    best = candidate
            if best is not None:
                ranked.append(best)
    ranked.sort(reverse=True)
    return ranked


def _apply_flip_to_model(model, name, index, bit):
    parameter = dict(model.named_parameters())[name]
    flat = parameter.data.view(-1)
    view = flat.numpy().view(np.uint32)
    view[index] ^= np.uint32(1) << np.uint32(bit)


def _sample_accuracy(model, images, labels):
    correct = 0
    with torch.no_grad():
        for start in range(0, len(labels), 200):
            end = min(len(labels), start + 200)
            correct += int(
                (model(images[start:end]).argmax(1) == labels[start:end])
                .sum()
                .item()
            )
    return correct / len(labels)


def find_bit_flips(model, images, labels):
    """Return a minimal adaptive list of legal one-bit weight lesions."""
    model.eval()
    selected, head_accuracy, used_scalars = _greedy_head_search(
        model, images, labels
    )
    if head_accuracy <= TARGET_SAMPLE_ACCURACY:
        return selected

    # Replay head flips into the supplied model before computing residual
    # gradients.  The harness evaluates a fresh state dict, so these mutations
    # are search-local only.
    for name, index, bit in selected:
        _apply_flip_to_model(model, name, index, bit)

    ranked = _gradient_candidates(model, images, labels, used_scalars)
    for _, name, index, bit in ranked:
        if len(selected) >= MAX_TOTAL_FLIPS:
            break
        scalar = (name, index)
        if scalar in used_scalars:
            continue
        _apply_flip_to_model(model, name, index, bit)
        selected.append((name, int(index), int(bit)))
        used_scalars.add(scalar)
        if _sample_accuracy(model, images, labels) <= TARGET_SAMPLE_ACCURACY:
            break

    return selected
