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
  };

  config = lib.mkIf cfg.enable {
    users.users.treningsdagbok = { isSystemUser = true; group = "treningsdagbok"; };
    users.groups.treningsdagbok.members = [ config.services.nginx.user ];

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
