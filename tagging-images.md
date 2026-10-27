# Git Tags → Docker Image Version Tags (GitHub Actions + GHCR)

## 1. Create and push a Git version tag

```bash
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
# or
git push --tags
```

## 2. Trigger workflow on Git tags

```yaml
on:
  push:
    branches: ["main"]
    tags:
      - "v*"
```

## 3. Use the Git tag as the Docker image tag

GitHub provides the tag name via `github.ref_name`.

```yaml
tags: |
  ghcr.io/<owner>/<image>:${{ github.ref_name }}
  ghcr.io/${{ steps.owner.outputs.owner }}/edhrec-deck-analyzer:${{ github.sha }}
```

## 4. Short SHA tag (cleaner)

GitHub doesn't provide a short SHA by default, but you can create one:

```yaml
- name: Set short SHA
  id: sha
  run: echo "short=${GITHUB_SHA::7}" >> $GITHUB_OUTPUT

- name: Build and Push
  uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: |
      ghcr.io/${{ steps.owner.outputs.owner }}/edhrec-deck-analyzer:latest
      ghcr.io/${{ steps.owner.outputs.owner }}/edhrec-deck-analyzer:${{ steps.sha.outputs.short }}
```

Produces: `:image:v1.2.3`

## 5. Tag both version and latest (recommended)

```yaml
tags: |
  ghcr.io/<owner>/<image>:${{ github.ref_name }}
  ghcr.io/<owner>/<image>:latest
```

## 6. Optional: remove the `v` prefix

```yaml
- run: echo "version=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

tags: |
  ghcr.io/<owner>/<image>:${{ steps.version.outputs.version }}
  ghcr.io/<owner>/<image>:latest
```

## 7. Recommended tagging strategy

| Tag            | Purpose              |
| -------------- | -------------------- |
| `1.2.3`        | Immutable release    |
| `latest`       | Most recent stable   |
| `sha-<commit>` | Debugging / rollback |

## Key takeaway

1. Push a Git tag (`vX.Y.Z`)
2. Workflow triggers on the tag
3. Docker image is automatically tagged with the same version
