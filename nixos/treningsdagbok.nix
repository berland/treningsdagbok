{ config, lib, pkgs, ... }:

# Usage (e.g. in configuration.nix):
#   imports = [ ./treningsdagbok.nix ];
#   services.treningsdagbok = {
#     enable = true;
#     domain = "trening.example.org";
#     src = /path/to/trening-ny;      # or fetchGit/fetchFromGitHub
#   };
let
  cfg = config.services.treningsdagbok;
  python = pkgs.python3.withPackages (ps: [ ps.flask ps.gunicorn ]);
  db = "/var/lib/treningsdagbok/trening.sqlite3";
  backupScript = pkgs.writeShellScript "treningsdagbok-backup" ''
    set -eu
    dir=${cfg.backup.directory}
    tmp="$dir/.in-progress.sqlite3"
    rm -f "$tmp"
    ${pkgs.sqlite}/bin/sqlite3 ${db} ".backup '$tmp'"
    test "$(${pkgs.sqlite}/bin/sqlite3 "$tmp" 'PRAGMA integrity_check')" = ok
    mv "$tmp" "$dir/trening-$(date +%F).sqlite3"
    find "$dir" -name 'trening-*.sqlite3' -mtime +${toString cfg.backup.keepDays} -delete
  '';
in
{
  options.services.treningsdagbok = {
    enable = lib.mkEnableOption "Treningsdagbok";
    src = lib.mkOption {
      type = lib.types.path;
      description = "Source directory of the app (contains src/treningsdagbok/).";
    };
    domain = lib.mkOption { type = lib.types.str; };
    enableACME = lib.mkOption { type = lib.types.bool; default = true; };
    socket = lib.mkOption {
      type = lib.types.str;
      default = "/run/treningsdagbok/gunicorn.sock";
    };
    backup = {
      enable = lib.mkOption { type = lib.types.bool; default = true; };
      directory = lib.mkOption {
        type = lib.types.str;
        default = "/var/backup/treningsdagbok";
        description = ''
          Where dated database snapshots are written. Readable by the
          treningsdagbok group, so add your backup/rsync user to that group.
        '';
      };
      keepDays = lib.mkOption { type = lib.types.int; default = 14; };
      calendar = lib.mkOption { type = lib.types.str; default = "*-*-* 03:00:00"; };
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.treningsdagbok = { isSystemUser = true; group = "treningsdagbok"; };
    users.groups.treningsdagbok.members = [ config.services.nginx.user ];

    systemd.tmpfiles.rules = lib.mkIf cfg.backup.enable [
      "d ${cfg.backup.directory} 0750 treningsdagbok treningsdagbok -"
    ];

    systemd.services.treningsdagbok-backup = lib.mkIf cfg.backup.enable {
      description = "Snapshot the Treningsdagbok SQLite database";
      serviceConfig = {
        Type = "oneshot";
        User = "treningsdagbok";
        Group = "treningsdagbok";
        UMask = "0027";
        StateDirectory = "treningsdagbok";
        ReadWritePaths = [ cfg.backup.directory ];
        ExecStart = backupScript;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      };
    };

    systemd.timers.treningsdagbok-backup = lib.mkIf cfg.backup.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.backup.calendar;
        Persistent = true;
        RandomizedDelaySec = "10m";
      };
    };

    systemd.services.treningsdagbok = {
      wantedBy = [ "multi-user.target" ];
      environment = {
        TRENING_DB = "/var/lib/treningsdagbok/trening.sqlite3";
        PYTHONPATH = "${cfg.src}/src";
      };
      serviceConfig = {
        User = "treningsdagbok";
        Group = "treningsdagbok";
        StateDirectory = "treningsdagbok";
        RuntimeDirectory = "treningsdagbok";
        UMask = "0007";
        ExecStart = "${python}/bin/gunicorn --workers 2 --bind unix:${cfg.socket} 'treningsdagbok:wsgi()'";
        Restart = "on-failure";
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      };
    };

    services.nginx = {
      enable = true;
      virtualHosts.${cfg.domain} = {
        enableACME = lib.mkDefault cfg.enableACME;
        forceSSL = lib.mkDefault cfg.enableACME;
        locations."/static/".alias = "${cfg.src}/src/treningsdagbok/static/";
        locations."/" = {
          proxyPass = "http://unix:${cfg.socket}";
          recommendedProxySettings = true;
        };
      };
    };
  };
}
