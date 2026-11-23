--------------------------- MODULE EngineSwitch ---------------------------
(*
  Formal TLA+ specification for Cloud Frugality Engine Switcher URL Resolution.
  Ref: https://learntla.com/index.html

  This specification proves that under all execution environments (Local development,
  AWS Lambda serverless, and arbitrary remote cloud reverse-proxies), the resolved
  navigation links for the Python and Rust engine switchers satisfy the following
  safety invariants:
  
  1. NoLocalhostOnRemote: Under AWS Lambda or remote environments, the switcher
     URLs NEVER evaluate to localhost or 127.0.0.1.
  2. ValidResolution: URLs resolve deterministically either to configured remote
     peer endpoints (Function URLs) or relative engine delegation queries.
  3. LocalDevPreserved: Local development defaults to dedicated ports (:8090 / :8091)
     when outside AWS Lambda.
*)

EXTENDS Naturals, TLC

CONSTANTS
    Environments,      \* {"LocalDev", "AWSLambda", "CustomRemote"}
    EnvVarStates,      \* {"Unset", "LocalhostVal", "RemoteVal"}
    HostTypes,         \* {"Localhost", "RemoteHost"}
    URLTargets         \* {"LocalhostPort8090", "LocalhostPort8091", "RemoteFunctionURL", "RelativeEngine"}

VARIABLES
    currentEnv,        \* Current runtime environment
    pyEnvVar,          \* PYTHON_WEB_URL environment variable state
    rustEnvVar,        \* RUST_WEB_URL environment variable state
    hostHeader,        \* Incoming HTTP Host header
    resolvedPyURL,     \* Output Python switcher target
    resolvedRustURL    \* Output Rust switcher target

vars == <<currentEnv, pyEnvVar, rustEnvVar, hostHeader, resolvedPyURL, resolvedRustURL>>

-----------------------------------------------------------------------------
(* Helper resolution operator representing the implementation logic *)

ResolvePython(env, pyVar, host) ==
    IF host = "Localhost" /\ env = "LocalDev" THEN
        IF pyVar = "RemoteVal" THEN "RemoteFunctionURL"
        ELSE "LocalhostPort8090"
    ELSE
        IF pyVar = "RemoteVal" THEN "RemoteFunctionURL"
        ELSE "RelativeEngine"

ResolveRust(env, rustVar, host) ==
    IF host = "Localhost" /\ env = "LocalDev" THEN
        IF rustVar = "RemoteVal" THEN "RemoteFunctionURL"
        ELSE "LocalhostPort8091"
    ELSE
        IF rustVar = "RemoteVal" THEN "RemoteFunctionURL"
        ELSE "RelativeEngine"

-----------------------------------------------------------------------------
(* Initial State: Any valid configuration before request arrival *)

Init ==
    /\ currentEnv \in Environments
    /\ pyEnvVar \in EnvVarStates
    /\ rustEnvVar \in EnvVarStates
    /\ hostHeader \in HostTypes
    /\ resolvedPyURL = "Unresolved"
    /\ resolvedRustURL = "Unresolved"

(* Actions *)

ProcessIncomingRequest ==
    /\ resolvedPyURL = "Unresolved"
    /\ resolvedRustURL = "Unresolved"
    /\ resolvedPyURL' = ResolvePython(currentEnv, pyEnvVar, hostHeader)
    /\ resolvedRustURL' = ResolveRust(currentEnv, rustEnvVar, hostHeader)
    /\ UNCHANGED <<currentEnv, pyEnvVar, rustEnvVar, hostHeader>>

ReconfigureEnv(newEnv, newPyVar, newRustVar, newHost) ==
    /\ newEnv \in Environments
    /\ newPyVar \in EnvVarStates
    /\ newRustVar \in EnvVarStates
    /\ newHost \in HostTypes
    /\ currentEnv' = newEnv
    /\ pyEnvVar' = newPyVar
    /\ rustEnvVar' = newRustVar
    /\ hostHeader' = newHost
    /\ resolvedPyURL' = "Unresolved"
    /\ resolvedRustURL' = "Unresolved"

Next ==
    \/ ProcessIncomingRequest
    \/ \E e \in Environments, p \in EnvVarStates, r \in EnvVarStates, h \in HostTypes:
         ReconfigureEnv(e, p, r, h)

-----------------------------------------------------------------------------
(* Invariants *)

TypeOK ==
    /\ currentEnv \in Environments
    /\ pyEnvVar \in EnvVarStates
    /\ rustEnvVar \in EnvVarStates
    /\ hostHeader \in HostTypes
    /\ resolvedPyURL \in (URLTargets \cup {"Unresolved"})
    /\ resolvedRustURL \in (URLTargets \cup {"Unresolved"})

(* Critical Invariant 1: No localhost links on AWS Lambda or Remote Hosts *)
NoLocalhostOnRemote ==
    (currentEnv \in {"AWSLambda", "CustomRemote"} \/ hostHeader = "RemoteHost") =>
        /\ resolvedPyURL /= "LocalhostPort8090"
        /\ resolvedPyURL /= "LocalhostPort8091"
        /\ resolvedRustURL /= "LocalhostPort8090"
        /\ resolvedRustURL /= "LocalhostPort8091"

(* Critical Invariant 2: Remote targets must be valid Function URLs or relative engine queries *)
ValidRemoteResolution ==
    (currentEnv = "AWSLambda" /\ resolvedPyURL /= "Unresolved") =>
        /\ resolvedPyURL \in {"RemoteFunctionURL", "RelativeEngine"}
        /\ resolvedRustURL \in {"RemoteFunctionURL", "RelativeEngine"}

(* Invariant 3: Clean fallback in local development when no remote overrides are provided *)
LocalDevDefault ==
    (currentEnv = "LocalDev" /\ hostHeader = "Localhost" /\ pyEnvVar = "Unset" /\ rustEnvVar = "Unset" /\ resolvedPyURL /= "Unresolved") =>
        /\ resolvedPyURL = "LocalhostPort8090"
        /\ resolvedRustURL = "LocalhostPort8091"

Spec == Init /\ [][Next]_vars

=============================================================================
