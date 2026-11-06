# alfslab-operator

Index: `.openshift-app.yaml` → `deploy/operator` (slim demo path).

Full install with PVC/secrets remains under `deploy/openshift/`.

Image: `quay.io/abach/vcenteremu:latest`

The slim operator deployment disables Kubernetes service-link environment
variables because the generated `VCENTEREMU_PORT=tcp://...` variable conflicts
with the application's numeric port setting.

Create the required API-password secret in the target namespace before applying
the operator manifests:

```bash
oc create secret generic vcenteremu-secret \
  --from-literal=VCENTEREMU_API_PASSWORD='<strong-password>'
```

The password must contain at least 12 characters. Credentials are intentionally
not stored in this repository.
