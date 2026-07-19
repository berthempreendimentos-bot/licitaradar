require("dotenv/config");
const { PrismaClient } = require("@prisma/client");

async function main() {
  const prisma = new PrismaClient({ datasourceUrl: process.env.DATABASE_URL });
  await prisma.$connect();
  console.log("Connected to database");

  const rows = await prisma.estoque.findMany({ take: 1 });
  console.log("Query result:", rows);

  await prisma.$disconnect();
}

main().catch((e) => {
  console.error("Error:", e.message);
  process.exit(1);
});
