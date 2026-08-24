import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image.
  output: "standalone",

  // The old routes still exist in people's bookmarks and in the API examples
  // this project printed before the rebuild. They move, permanently.
  redirects() {
    const at = (path: string) => ({
      source: `/companies/:companyId${path}`,
      destination: `/c/:companyId${path}`,
      permanent: true,
    });
    return [
      { source: "/companies/:companyId", destination: "/c/:companyId", permanent: true },
      // Renamed as well as moved: the vocabulary changed with the model.
      {
        source: "/companies/:companyId/people",
        destination: "/c/:companyId/agents",
        permanent: true,
      },
      {
        source: "/companies/:companyId/people/:employeeId",
        destination: "/c/:companyId/agents/:employeeId",
        permanent: true,
      },
      {
        source: "/companies/:companyId/projects",
        destination: "/c/:companyId/work",
        permanent: true,
      },
      {
        source: "/companies/:companyId/projects/:projectId",
        destination: "/c/:companyId/work/:projectId",
        permanent: true,
      },
      { source: "/companies/:companyId/wiki", destination: "/c/:companyId/knowledge", permanent: true },
      {
        source: "/companies/:companyId/wiki/:documentId",
        destination: "/c/:companyId/knowledge/:documentId",
        permanent: true,
      },
      { source: "/companies/:companyId/chat", destination: "/c/:companyId/rooms", permanent: true },
      { source: "/companies/:companyId/code", destination: "/c/:companyId/studio", permanent: true },
      at("/settings"),
    ];
  },
};

export default nextConfig;
