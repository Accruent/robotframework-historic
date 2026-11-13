# Release, Smoke Check and Rollback

Production runs in AKS: context `Legion-a6d6a7a`, namespace `legion-historic`, deployment `rfhistoric-depl`, container `rfhistoric-app`, URL https://rfhistoric-qe-tools.accruentsystems.com. The deployment tracks `proget.accruentsystems.com/qe_docker/library/rfhistoric:latest` with `imagePullPolicy: Always`.

## Release

1. Bump `VERSION` in `version.py`. Without a bump, the publish overwrites the previous `:<VERSION>` tag and removes your rollback target.
2. Merge to `master`. `Build and Publish Docker Image` pushes `:latest` and `:<VERSION>`.
3. Record the digest currently running (your rollback target):

   ```powershell
   kubectl --context Legion-a6d6a7a -n legion-historic get pod -l app=rfhistoric-app -o jsonpath="{.items[*].status.containerStatuses[*].imageID}"
   ```

4. Restart the deployment to pull the new `:latest`:

   ```powershell
   kubectl --context Legion-a6d6a7a -n legion-historic rollout restart deploy/rfhistoric-depl
   ```

   ```powershell
   kubectl --context Legion-a6d6a7a -n legion-historic rollout status deploy/rfhistoric-depl
   ```

5. Run the post-release smoke check below.
6. Publish the Release Drafter draft on the Releases page. Set the tag and title to `v<VERSION>` (from `version.py`) if they differ, and mark it Latest.

## Post-release smoke check

Set the project to probe once per session. Use a project database name listed on the home page that has executions, and an execution id from the `metrics/<id>` links on `/<project db>/ehistoric`:

```powershell
$base='https://rfhistoric-qe-tools.accruentsystems.com'; $db='<project db>'; $eid='<execution id>'
```

Expect 200 for each:

```powershell
foreach($p in '/',"/$db/dashboard","/$db/metrics/$eid","/$db/compare"){ "$p " + (Invoke-WebRequest "$base$p" -UseBasicParsing -SkipHttpErrorCheck).StatusCode }
```

Expect 403 (unauthenticated delete is blocked):

```powershell
(Invoke-WebRequest "$base/$db/edelete/$eid" -UseBasicParsing -SkipHttpErrorCheck).StatusCode
```

Expect no output (reads the newest pod; `logs deploy/...` can pick a terminating old pod):

```powershell
kubectl --context Legion-a6d6a7a -n legion-historic logs (kubectl --context Legion-a6d6a7a -n legion-historic get pod -l app=rfhistoric-app --sort-by=.metadata.creationTimestamp -o name | Select-Object -Last 1) | Select-String Traceback
```

## Rollback

`kubectl rollout undo` does not restore the previous image, because the deployment spec still says `:latest`. Pin the image instead, using the previous version tag or the digest recorded in Release step 3:

```powershell
kubectl --context Legion-a6d6a7a -n legion-historic set image deploy/rfhistoric-depl rfhistoric-app=proget.accruentsystems.com/qe_docker/library/rfhistoric:<previous VERSION>
```

```powershell
kubectl --context Legion-a6d6a7a -n legion-historic set image deploy/rfhistoric-depl rfhistoric-app=proget.accruentsystems.com/qe_docker/library/rfhistoric@sha256:<recorded digest>
```

Then rerun the smoke check. After a fixed release is published, return the deployment to `:latest`:

```powershell
kubectl --context Legion-a6d6a7a -n legion-historic set image deploy/rfhistoric-depl rfhistoric-app=proget.accruentsystems.com/qe_docker/library/rfhistoric:latest
```

## Dependency updates

1. Dependabot opens one grouped PR per ecosystem (`pip`, `github-actions`) each Monday.
2. `PR Build Check / build-and-smoke` must pass.
3. Merge, bump `version.py` (same PR or a follow-up), and release as above.

Merge these PRs regularly. GitHub pauses Dependabot version updates after prolonged inactivity.
