locals { stage = "/home/${var.user}/.origin-certificate-upload" }
resource "terraform_data" "material" {
  triggers_replace = [var.config.material_version, filesha256(var.config.certificate_file), filesha256(var.config.client_ca_file)]
  connection {
    type        = "ssh"
    host        = var.host
    user        = var.user
    private_key = var.ssh_private_key
    host_key    = var.config.ssh_host_key
    timeout     = "10m"
  }
  provisioner "remote-exec" {
    inline = ["install -d -m 0700 ${local.stage}", "rm -f ${local.stage}/key.pem ${local.stage}/certificate.pem ${local.stage}/client-ca.pem"]
  }
  provisioner "file" {
    content     = file(var.config.certificate_file)
    destination = "${local.stage}/certificate.pem"
  }
  provisioner "file" {
    content     = file(var.config.client_ca_file)
    destination = "${local.stage}/client-ca.pem"
  }
  provisioner "file" {
    content     = var.private_key
    destination = "${local.stage}/key.pem"
  }
  provisioner "remote-exec" {
    inline = ["sudo /usr/local/bin/origin-install-certificate ${local.stage}"]
  }
}
